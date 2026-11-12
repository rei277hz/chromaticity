"""Transform mdBook's print document into the static, paged book source."""

from dataclasses import dataclass
import copy
import hashlib
import html as html_stdlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit, urlunsplit

from lxml import etree, html

from pg_book_build import parts as part_numbering
from pg_book_build import site as site_builder


IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


@dataclass
class EditionDocument:
    language: str
    title: str
    parts: list
    chapters: list
    figures: list
    book_html: Path
    media_dir: Path
    math_expressions: int


def _slug(value):
    value = re.sub(r"[^\w-]+", "-", value.strip().lower(), flags=re.UNICODE)
    return re.sub(r"-+", "-", value).strip("-") or "item"


def _summary_items(book_root, language):
    source = Path(book_root) / ("src" if language == "en" else language)
    summary_path = source / "SUMMARY.md"
    lines = summary_path.read_text(encoding="utf-8").splitlines()
    items = []
    saw_title = False
    part_index = -1
    active_part = None
    stack = []

    for line in lines:
        heading = re.match(r"^#\s+(.+?)\s*$", line)
        if heading:
            if not saw_title:
                saw_title = True
                continue
            part_index += 1
            active_part = {"index": part_index, "title": heading.group(1).strip(), "chapters": []}
            items.append({"PartTitle": active_part["title"], "part_index": part_index})
            stack = []
            continue

        match = re.match(r"^(\s*)(?:[-*]\s+)?\[([^\]]+)\]\(([^)#]+\.md)(?:#[^)]*)?\)\s*$", line)
        if not match:
            continue

        indent = len(match.group(1).expandtabs(4))
        name, path = match.group(2).strip(), PurePosixPath(match.group(3)).as_posix()
        chapter = {
            "name": name,
            "path": path,
            "number": None if path == "README.md" else [],
            "sub_items": [],
            "part_index": active_part["index"] if active_part else None,
            "depth": 1,
        }
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if indent and stack:
            parent = stack[-1][1]
            chapter["depth"] = parent["depth"] + 1
            parent["sub_items"].append({"Chapter": chapter})
        else:
            items.append({"Chapter": chapter})
            if active_part:
                active_part["chapters"].append(chapter)
        stack.append((indent, chapter))

    if not saw_title:
        raise ValueError(f"Missing SUMMARY title: {summary_path}")
    numbered = part_numbering.number_parts({"items": items})
    parts = []
    chapters = []
    active_part = None

    def flatten(chapter, inherited_part):
        part_index = chapter.get("part_index", inherited_part)
        chapter["number"] = chapter["number"] if chapter["number"] is not None else None
        chapters.append({
            "path": chapter["path"],
            "summary_title": chapter["name"],
            "number": tuple(chapter["number"]) if chapter["number"] is not None else None,
            "depth": chapter["depth"],
            "part_index": part_index,
        })
        for child in chapter["sub_items"]:
            flatten(child["Chapter"], part_index)

    for item in numbered["items"]:
        if "PartTitle" in item:
            active_part = {"index": item["part_index"], "title": item["PartTitle"], "chapters": []}
            parts.append(active_part)
        elif "Chapter" in item:
            flatten(item["Chapter"], active_part["index"] if active_part else None)

    for part in parts:
        part["chapters"] = [chapter for chapter in chapters if chapter["part_index"] == part["index"]]
    return source, chapters, parts


def _render_math(main, node, renderer, katex_js):
    expressions = []
    elements = main.xpath(".//*[@data-tex]")
    for element in elements:
        expressions.append({
            "tex": element.get("data-tex", ""),
            "display": "grade-equation" in (element.get("class") or "").split(),
        })
    if not expressions:
        return 0

    try:
        rendered = subprocess.run(
            [str(Path(node).resolve()), str(Path(renderer).resolve()), str(Path(katex_js).resolve())],
            input=json.dumps(expressions, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as error:
        details = error.stderr.strip()
        raise RuntimeError(f"KaTeX rendering failed: {details[-4000:]}") from error
    output = json.loads(rendered.stdout)
    if len(output) != len(elements):
        raise ValueError("KaTeX returned a different number of expressions than requested")
    for element, markup in zip(elements, output):
        element.attrib.pop("data-tex", None)
        tail = element.tail
        element.text = None
        for child in list(element):
            element.remove(child)
        fragment = html.fragments_fromstring(markup)
        for node_fragment in fragment:
            if isinstance(node_fragment, str):
                element.text = (element.text or "") + node_fragment
            else:
                element.append(node_fragment)
        element.tail = tail
    if main.xpath(".//*[@data-tex]"):
        raise ValueError("Unrendered TeX remains in the print document")
    return len(expressions)


def _normalize_screen_content(main):
    for element in list(main.xpath(".//script|.//style|.//iframe|.//video|.//audio|.//source|.//button|.//input")):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)

    for element in list(main.xpath(".//nav|.//footer|.//*[contains(concat(' ', normalize-space(@class), ' '), ' chapter-nav ') or contains(concat(' ', normalize-space(@class), ' '), ' video-embed ')]")):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)

    for label in list(main.xpath(".//label[contains(concat(' ', normalize-space(@class), ' '), ' checkbox-label ')]")):
        parent = label.getparent()
        if parent is None:
            continue
        anchors = label.xpath(".//a[.//img]")
        replacement = copy.deepcopy(anchors[0]) if anchors else None
        if replacement is None:
            images = label.xpath(".//img")
            if images:
                replacement = etree.Element("span")
                replacement.append(images[0])
        if replacement is None:
            parent.remove(label)
        else:
            replacement.tail = label.tail
            parent.replace(label, replacement)

    for image in main.xpath(".//img"):
        still = image.get("data-still")
        if still:
            image.set("src", still)
        image.attrib.pop("data-still", None)
        image.attrib.pop("loading", None)

    for element in list(main.xpath(".//div[@style]")):
        style = (element.get("style") or "").lower()
        if "break-before" in style or "page-break-before" in style:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)

    for heading in main.xpath(".//h1"):
        for anchor in list(heading.xpath("./a[contains(concat(' ', normalize-space(@class), ' '), ' header ')]")):
            anchor.drop_tag()


def _figure_caption_text(caption):
    parts = []
    for element in caption.iter():
        if element is caption:
            if element.text:
                parts.append(element.text)
            continue
        if "figure-number" in (element.get("class") or "").split():
            if element.tail:
                parts.append(element.tail)
            continue
        if element.text:
            parts.append(element.text)
        if element.tail:
            parts.append(element.tail)
    return " ".join(" ".join(parts).split())


def _normalize_figures(section, chapter, language):
    for caption in list(section.xpath(".//p[contains(concat(' ', normalize-space(@class), ' '), ' figure-caption ')]")):
        previous = caption.getprevious()
        if previous is None or not previous.xpath(".//img"):
            continue
        parent = caption.getparent()
        index = parent.index(previous)
        parent.remove(previous)
        parent.remove(caption)
        figure = etree.Element("figure")
        parent.insert(index, figure)
        figure.append(previous)
        caption.tag = "figcaption"
        caption.attrib.pop("class", None)
        figure.append(caption)

    for paragraph in list(section.xpath(".//p[.//img[not(ancestor::figure)]]")):
        parent = paragraph.getparent()
        if parent is None or paragraph.xpath("ancestor::figure"):
            continue
        index = parent.index(paragraph)
        parent.remove(paragraph)
        figure = etree.Element("figure")
        parent.insert(index, figure)
        figure.append(paragraph)
        caption = etree.SubElement(figure, "figcaption")
        alt = " ".join(" ".join((image.get("alt") or "").split()) for image in figure.xpath(".//img"))
        caption.text = alt or chapter["title"]

    figures = []
    for index, figure in enumerate(section.xpath(".//figure"), start=1):
        chapter_number = ".".join(map(str, chapter["number"])) if chapter["number"] else "0"
        figure_number = f"{chapter_number}.{index}"
        figure_id = figure.get("id") or f"figure-{_slug(chapter['id'])}-{index}"
        figure.set("id", figure_id)
        captions = figure.xpath("./figcaption")
        if captions:
            caption = captions[0]
        else:
            caption = etree.SubElement(figure, "figcaption")
            caption.text = chapter["title"]
        for old in list(caption.xpath("./span[contains(concat(' ', normalize-space(@class), ' '), ' figure-number ')]")):
            caption.remove(old)
        label = etree.Element("span", attrib={"class": "figure-number"})
        label.text = ("图 " if language == "zh-Hans" else "Figure ") + figure_number
        label.tail = " " + (caption.text or "")
        caption.text = None
        caption.insert(0, label)
        figures.append({
            "id": figure_id,
            "chapter_id": chapter["id"],
            "number": figure_number,
            "caption": _figure_caption_text(caption),
        })
    return figures


def _copy_media(main, site_root, origin, edition_output, in_book_ids):
    media_dir = edition_output / "media"
    refs = []
    for element in main.xpath(".//*[@src] | .//*[@poster] | .//a[@href]"):
        attr = "src" if element.get("src") else "poster" if element.get("poster") else "href"
        value = element.get(attr) or ""
        url = urlsplit(value)
        if attr == "href" and not url.scheme and not url.netloc and url.fragment:
            candidate = (origin.parent / unquote(url.path or origin.name)).resolve()
            if candidate == origin.resolve() and unquote(url.fragment) in in_book_ids:
                element.set(attr, "#" + url.fragment)
                continue
        if url.scheme or url.netloc or not url.path:
            continue
        target_path = (origin.parent / unquote(url.path)).resolve()
        if not target_path.is_relative_to(site_root.resolve()):
            raise ValueError(f"Print resource escapes the site tree: {value}")
        if target_path.is_dir():
            target_path = target_path / "index.html"
        if not target_path.is_file():
            raise ValueError(f"Missing print resource referenced by {origin.name}: {value}")
        relative_site_path = target_path.relative_to(site_root.resolve())
        if target_path.suffix.lower() in IMAGE_SUFFIXES:
            relative_media = PurePosixPath(relative_site_path.as_posix())
            destination = media_dir.joinpath(*relative_media.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target_path, destination)
            new_value = (PurePosixPath("media") / relative_media).as_posix()
            element.set(attr, new_value)
            refs.append((new_value, destination))
        elif attr == "href":
            element.set(attr, urlunsplit(("https", "rei277hz.github.io", "/perceptual-grade/" + relative_site_path.as_posix(), url.query, url.fragment)))
        else:
            raise ValueError(f"Non-image local source is unsupported in print output: {value}")
    return media_dir, refs


def _build_toc(chapters, parts, language):
    title = "目录" if language == "zh-Hans" else "Contents"
    rows = [f'<nav class="toc" aria-label="{title}"><h1>{title}</h1><ol>']
    part_by_index = {part["index"]: part for part in parts}
    emitted_parts = set()
    for chapter in chapters:
        part_index = chapter["part_index"]
        if part_index is not None and part_index not in emitted_parts:
            part = part_by_index[part_index]
            rows.append(f'<li class="part-entry"><a href="#{part["id"]}">{html_stdlib.escape(part["title"])}</a></li>')
            emitted_parts.add(part_index)
        number = ".".join(map(str, chapter["number"])) if chapter["number"] else ""
        prefix = f"{number}. " if number else ""
        rows.append(
            f'<li class="chapter-entry" data-depth="{chapter["depth"]}">'
            f'<a href="#{chapter["id"]}">{html_stdlib.escape(prefix + chapter["title"])}</a></li>'
        )
    rows.append("</ol></nav>")
    return "".join(rows)


def _build_figure_list(figures, language):
    if not figures:
        return ""
    title = "插图目录" if language == "zh-Hans" else "Figures"
    rows = [f'<nav class="figure-list" aria-label="{title}"><h1>{title}</h1><ol>']
    for figure in figures:
        label = ("图 " if language == "zh-Hans" else "Figure ") + figure["number"]
        caption = " ".join((figure["caption"] or "").split())
        rows.append(f'<li><a href="#{figure["id"]}">{html_stdlib.escape(label + " " + caption)}</a></li>')
    rows.append("</ol></nav>")
    return "".join(rows)


def build_document(site_root, book_root, language, front_matter, output_dir, node, math_renderer, katex_js, katex_css, katex_package, noto_package, font_sans, font_mono, theme_dir):
    site_root = Path(site_root).resolve()
    book_root = Path(book_root).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source, chapters, parts = _summary_items(book_root, language)
    if site_builder.check_chapters(book_root, language) != [chapter["path"] for chapter in chapters]:
        raise ValueError(f"SUMMARY chapter paths differ from assembled sources: {language}")

    print_page = site_root / language / "print.html"
    if not print_page.is_file():
        raise ValueError(f"Missing mdBook print output: {print_page}")
    document = html.document_fromstring(print_page.read_bytes())
    main_nodes = document.xpath("//main")
    if len(main_nodes) != 1:
        raise ValueError(f"Expected one main content element in {print_page}")
    main = main_nodes[0]
    for footer in list(main.xpath(".//footer")):
        footer.getparent().remove(footer)
    _normalize_screen_content(main)
    math_expressions = _render_math(main, node, math_renderer, katex_js)

    headings = main.xpath(".//h1")
    if len(headings) != len(chapters):
        raise ValueError(f"mdBook output has {len(headings)} chapter headings; SUMMARY has {len(chapters)} entries for {language}")
    heading_ids = [heading.get("id") for heading in headings]
    if any(not value for value in heading_ids) or len(heading_ids) != len(set(heading_ids)):
        raise ValueError("mdBook chapter headings require unique stable ids")

    child_groups = []
    current = None
    preamble = []
    for child in list(main):
        if not isinstance(child.tag, str):
            continue
        if child.tag.lower() == "h1":
            current = {"heading": child, "content": []}
            child_groups.append(current)
        elif current is None:
            preamble.append(child)
        else:
            current["content"].append(child)
    if len(child_groups) != len(chapters):
        raise ValueError("Could not split mdBook print content at chapter headings")

    prepared_chapters = []
    all_figures = []
    for metadata, group in zip(chapters, child_groups):
        heading = group["heading"]
        chapter = dict(metadata)
        chapter["id"] = heading.get("id")
        chapter["title"] = " ".join("".join(heading.itertext()).split())
        section = etree.Element("section", attrib={
            "class": "chapter",
            "id": "chapter-section-" + chapter["id"],
            "data-depth": str(chapter["depth"]),
        })
        if chapter["number"]:
            number = ".".join(map(str, chapter["number"]))
            section.set("data-number", number)
        heading.set("class", "chapter-title")
        if chapter["number"]:
            number_node = etree.Element("span", attrib={"class": "chapter-number"})
            number_node.text = ".".join(map(str, chapter["number"]))
            number_node.tail = " " + (heading.text or "").lstrip()
            heading.text = None
            heading.insert(0, number_node)
        section.append(heading)
        for element in group["content"]:
            if element.getparent() is main:
                main.remove(element)
            section.append(element)
        chapter["section"] = section
        chapter["figures"] = _normalize_figures(section, chapter, language)
        all_figures.extend(chapter["figures"])
        prepared_chapters.append(chapter)

    parts_by_index = {part["index"]: dict(part) for part in parts}
    for part in parts_by_index.values():
        part["id"] = f"part-{part['index'] + 1}-{_slug(part['title'])}"
    content_items = []
    if preamble:
        for element in preamble:
            if element.getparent() is main:
                main.remove(element)
        content_items.extend(preamble)
    for chapter in prepared_chapters:
        part_index = chapter["part_index"]
        if part_index is not None and not any(item.get("part_index") == part_index for item in content_items if isinstance(item, dict)):
            part = parts_by_index[part_index]
            part_section = etree.Element("section", attrib={"class": "part", "id": part["id"]})
            title = etree.SubElement(part_section, "h1", attrib={"class": "part-title"})
            part_number = etree.SubElement(title, "span", attrib={"class": "part-number"})
            part_number.text = ("第 " + str(part_index + 1) + " 部分") if language == "zh-Hans" else ("Part " + str(part_index + 1))
            part_number.tail = " "
            part_name = etree.SubElement(title, "span", attrib={"class": "part-name"})
            part_name.text = part["title"]
            part["section"] = part_section
            content_items.append(part_section)
            content_items.append({"part_index": part_index})
        content_items.append(chapter["section"])

    part_entries = []
    for part in parts_by_index.values():
        part_entries.append({"index": part["index"], "title": part["title"], "id": part["id"]})

    # Copy only referenced local images; local historical downloads become site links.
    content_root = etree.Element("div")
    for item in content_items:
        if isinstance(item, dict):
            continue
        content_root.append(item)
    in_book_ids = {element.get("id") for element in content_root.iter() if element.get("id")}
    media_dir, media_refs = _copy_media(content_root, site_root, print_page, output_dir, in_book_ids)

    for stylesheet in ("print.css", "epub.css", "tokens.css"):
        shutil.copyfile(Path(theme_dir) / stylesheet, output_dir / stylesheet)
    font_dir = output_dir / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(font_sans, font_dir / "pontano-sans.woff2")
    shutil.copyfile(font_mono, font_dir / "roboto-mono.woff2")
    font_css = (
        '@font-face{font-family:"Pontano Sans";font-style:normal;font-weight:300 700;'
        'src:url("fonts/pontano-sans.woff2") format("woff2");}\n'
        '@font-face{font-family:"Roboto Mono";font-style:normal;font-weight:100 700;'
        'src:url("fonts/roboto-mono.woff2") format("woff2");}\n'
    )
    (output_dir / "fonts.css").write_text(font_css, encoding="utf-8")

    katex_root = output_dir / "katex"
    katex_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(katex_css, katex_root / "katex.min.css")
    # Extract only KaTeX font assets and its license from the pinned package.
    import tarfile
    with tarfile.open(katex_package, "r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                continue
            if path.parts[:3] == ("package", "dist", "fonts") and path.suffix in {".woff2", ".woff", ".ttf"}:
                relative = Path(*path.parts[3:])
                destination = katex_root / "fonts" / relative
            elif path.parts == ("package", "LICENSE"):
                destination = katex_root / "LICENSE"
            else:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Could not read pinned KaTeX resource: {member.name}")
            destination.write_bytes(source.read())

    noto_root = font_dir / "noto"
    noto_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(noto_package, "r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                continue
            if path.parts == ("package", "index.css"):
                relative = Path("index.css")
            elif path.parts == ("package", "LICENSE"):
                relative = Path("LICENSE")
            elif path.parts[:2] == ("package", "files") and path.suffix == ".woff2":
                relative = Path("files", *path.parts[2:])
            else:
                continue
            destination = noto_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Could not read pinned Noto font resource: {member.name}")
            destination.write_bytes(source.read())

    # KaTeX CSS font URLs stay package-relative; Noto's index.css uses ./files/.
    import tomllib
    with (book_root / "book.toml").open("rb") as stream:
        title = tomllib.load(stream)["book"]["title"]
    chapter_sections = []
    for chapter in prepared_chapters:
        chapter_sections.append(etree.tostring(chapter["section"], encoding="unicode", method="html"))
    book_html = output_dir / "book.html"
    front = Path(front_matter).read_text(encoding="utf-8")
    toc = _build_toc(prepared_chapters, part_entries, language)
    figure_list = _build_figure_list(all_figures, language)
    content_html = "".join(etree.tostring(item, encoding="unicode", method="html") for item in content_root)
    html_text = (
        '<!doctype html><html lang="' + html_stdlib.escape(language, quote=True) + '"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>' + title + '</title>'
        '<link rel="stylesheet" href="fonts.css"><link rel="stylesheet" href="fonts/noto/index.css">'
        '<link rel="stylesheet" href="katex/katex.min.css"><link rel="stylesheet" href="print.css">'
        '</head><body class="book"><div class="front-matter">' + front + '</div>'
        + toc + figure_list + '<main class="book-content">' + content_html + '</main></body></html>'
    )
    book_html.write_text(html_text, encoding="utf-8")

    # Keep a complete element tree for EPUB generation, including generated front matter and navigation.
    epub_root = html.document_fromstring(html_text)
    epub_content = epub_root.xpath("//main[@class='book-content']")[0]
    epub_chapters = []
    for chapter, section in zip(prepared_chapters, epub_content.xpath("./section[contains(concat(' ', normalize-space(@class), ' '), ' chapter ')]")):
        chapter_copy = dict(chapter)
        chapter_copy["section"] = section
        epub_chapters.append(chapter_copy)
    epub_parts = []
    for part in part_entries:
        matches = epub_content.xpath(f"./section[@id='{part['id']}']")
        epub_parts.append(dict(part, section=matches[0] if matches else None))

    return EditionDocument(
        language=language,
        title=title,
        parts=epub_parts,
        chapters=epub_chapters,
        figures=all_figures,
        book_html=book_html,
        media_dir=media_dir,
        math_expressions=math_expressions,
    )
