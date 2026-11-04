"""Compose replaceable Blender/Resolve screenshots into reader-facing figures."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from pg_book_generators.figure_common import manifest


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots',type=Path,required=True);parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args(argv)
    spec=json.loads(args.spec.read_text())
    missing=sorted({panel['file'] for figure in spec['figures'] for panel in figure['panels'] if not (args.screenshots/panel['file']).is_file()})
    if missing:raise ValueError('Missing required screenshot sources: '+', '.join(missing))
    images=args.output_dir/'images';images.mkdir(parents=True,exist_ok=True)
    font=ImageFont.load_default(size=18);small=ImageFont.load_default(size=14);inputs=[args.spec,Path(__file__)]
    for figure in spec['figures']:
        columns=figure['columns'];panels=figure['panels'];width=500;gap=16;label_height=35
        cells=[]
        for panel in panels:
            path=args.screenshots/panel['file'];inputs.append(path)
            with Image.open(path) as raw:
                image=raw.convert('RGB');image.thumbnail((width,360),Image.Resampling.LANCZOS);cells.append((panel,image.copy()))
        row_heights=[max(image.height for _,image in cells[i:i+columns])+label_height for i in range(0,len(cells),columns)]
        sheet=Image.new('RGB',(columns*width+(columns+1)*gap,62+sum(row_heights)+gap*(len(row_heights)+1)),'#f7f7f4')
        draw=ImageDraw.Draw(sheet);draw.text((gap,16),figure['title'],font=font,fill='#343434');y=62
        for row,height in enumerate(row_heights):
            for col,(panel,image) in enumerate(cells[row*columns:(row+1)*columns]):
                x=gap+col*(width+gap);draw.text((x,y),panel['label'],font=small,fill='#626262')
                sheet.paste(image,(x+(width-image.width)//2,y+label_height))
            y+=height+gap
        sheet.save(images/(figure['name']+'.png'))
    manifest(args.output_dir,inputs,'compound host screenshots',
             {'docs/data': args.spec.parent, 'docs/media/screenshots': args.screenshots,
              'generators': Path(__file__).parent})


if __name__=='__main__':main()
