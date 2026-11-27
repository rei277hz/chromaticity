"""Host-adapted publication of complete Grade parameter-image banks."""

from dataclasses import dataclass, field
from typing import Any, Callable

from ...kernel import Settings
from ...kernel.stage2_bindings import (
    PARAMETER_ACTIVE_BANK, PARAMETER_BANK_BINDINGS, PARAMETER_GENERATION,
    PARAMETER_IMAGE, PARAMETER_ROLE,
)
from ...kernel.stage2_parameters import (
    PARAMETER_CONTENT_SIGNATURE, PARAMETER_ROLE_SHAPES, PARAMETER_ROLES,
    PARAMETER_SCHEMA,
    bind_parameter_bank, parameter_bank_images, parameter_bank_pair_images,
    parameter_bundle_receipt_matches,
    parameter_content_signature, parameter_image_matches, prepare_parameters,
    set_parameter_bundle_signature,
)
from ...runtime.image_publication import write_metadata
from .bank_publication import run_bank_publication
from .policy import node as node_policy
from .resources import OWNER as PARAMETER_OWNER
from .resources import OWNER_NODE as PARAMETER_OWNER_NODE
from .resources import SIGNATURE as PARAMETER_SIGNATURE


@dataclass(frozen=True)
class GradePublicationOperations:
    bpy: Any
    lifecycle: Any
    node_stores: dict
    resources: Any
    all_grade_nodes: Callable[[], tuple]
    kernel_for_node: Callable[[Any], Any]
    snapshot_values: Callable[[Any], Any]
    preparation_signature: Callable[[Any, str], str]
    signature: Callable[[str, Any, str], str]
    parameter_image_content_matches: Callable[[Any], bool]
    parameter_role_receipt_matches: Callable[[Any, str, str], bool]
    write_grade_parameters: Callable[[Any, Any], None]
    pack_grade_parameters: Callable[[Any], None]
    parameter_kernel_structure_valid: Callable[[Any], bool]
    build_kernel: Callable[..., Any]
    set_parameter_selector: Callable[[Any, int], None]
    read_parameter_selector: Callable[[Any], int]
    replace_node_kernel: Callable[[Any, Any], Any]
    dispatch: Callable[..., list]
    playback_preview: Callable[[dict, Any], bool]
    tag_compositor_outputs: Callable[[tuple], None]
    invalidate_grade_parameters: Callable[[Any], None]
    record_compositor_bindings: Callable[[tuple], Any]
    restore_compositor_bindings: Callable[[Any], None]
    fail_installation: Callable[..., list]
    publication_failure: Callable[..., tuple]
    retire_kernels: Callable[[tuple], list]
    remove_parameter_image: Callable[[Any], None]
    kernel_signature_key: str


@dataclass
class PublicationTransaction:
    previous_trees: dict
    outer_before: tuple
    kernels: dict | None = None
    receipt_before: Any = None
    metadata_before: tuple = field(default_factory=tuple)


def publish_grade_parameters(operations, source, authorized_records, prepared, *,
                             admitted, playback_session=None, recovery=None):
    """Stage, select, and deliver one complete fixed-bank generation."""
    users = tuple(
        record for record in authorized_records
        if record.get("source") is source
        and operations.lifecycle.admits(recovery, record["node"].as_pointer())
        and operations.node_stores.get(record["node"].as_pointer()) is record
    )
    if not users:
        return ()

    created, failures = [], []
    resources = operations.resources
    resource = resources.resource(users[0]["node"], prepared.space)
    if recovery is not None and resource.banks is not None:
        for node in operations.all_grade_nodes():
            if operations.lifecycle.admits(recovery, node.as_pointer()):
                continue
            kernel = operations.kernel_for_node(node)
            if kernel is not None and any(
                    kernel.get(key) in resource.banks for key in PARAMETER_BANK_BINDINGS):
                return operations.publication_failure(
                    users,
                    RuntimeError("Render Grade bank is shared with nodes outside this preflight"),
                    recovery=recovery,
                )

    settings = Settings(
        linear=prepared.linear.settings,
        tone=prepared.tone.settings,
        color=prepared.color.settings,
        space=prepared.space,
    )
    values = operations.snapshot_values(settings)
    preparation_signature = operations.preparation_signature(values, prepared.space)
    old_active = resource.active_bank if resource.active_bank in (0, 1) else 0
    old_generation = resource.generation if resource.generation is not None else 0
    generation = resources.next_generation(resource)
    active_valid = (
        resource.banks is None
        or operations.parameter_image_content_matches(resource.banks[old_active])
    )
    if playback_session is not None and not active_valid and any(
            operations.signature(record["node"].id_data.bl_idname, values, prepared.space)
            != record["state"].desired_signature
            for record in users):
        return operations.publication_failure(
            users, RuntimeError("Grade parameter bank is corrupt"), recovery=recovery,
        )

    transaction = PublicationTransaction(
        previous_trees=dict(resource.trees),
        outer_before=tuple(
            (record["node"], operations.kernel_for_node(record["node"]))
            for record in users
        ),
    )

    def make_image(bank, role):
        height, width, _channels = PARAMETER_ROLE_SHAPES[role]
        image = operations.bpy.data.images.new(
            f"Perceptual Grade {role} bank {bank}",
            width=width, height=height,
            alpha=True, float_buffer=True,
        )
        image.colorspace_settings.name = "Non-Color"
        image.alpha_mode = "CHANNEL_PACKED"
        image.use_half_precision = False
        image.file_format = "OPEN_EXR"
        image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
        image[PARAMETER_ROLE] = role
        image["_perceptual_grade_image"] = True
        return image

    def pack_role(image, role, pixels, content_signature, *, force=False):
        if (not force
                and operations.parameter_role_receipt_matches(
                    image, role, content_signature)
                and parameter_image_matches(image, content_signature, bundle=False)):
            return True
        image[PARAMETER_IMAGE] = PARAMETER_SCHEMA
        image[PARAMETER_ROLE] = role
        image["_perceptual_grade_image"] = True
        operations.write_grade_parameters(image, pixels)
        operations.pack_grade_parameters(image)
        if image.packed_file is None or image.is_dirty:
            return False
        image[PARAMETER_CONTENT_SIGNATURE] = content_signature
        if role != "parameter" and PARAMETER_SIGNATURE in image:
            del image[PARAMETER_SIGNATURE]
        return parameter_image_matches(image, content_signature, bundle=False)

    def pack_bank(primary, parameters, content_signatures, signature, *, force=False):
        role_images = parameter_bank_images(primary)
        if not all(
                pack_role(role_images[role], role, parameters.roles[role],
                          content_signatures[role], force=force)
                for role in PARAMETER_ROLES):
            return False
        set_parameter_bundle_signature(primary, content_signatures)
        primary[PARAMETER_SIGNATURE] = signature
        return True

    def stage(candidate_bank, _errors, *, repair=False):
        parameters = prepared.parameters or prepare_parameters(prepared)
        content_signatures = {
            role: parameter_content_signature(parameters.roles[role])
            for role in PARAMETER_ROLES
        }
        banks = resource.banks
        # A native Image can disappear between a failed publication rollback
        # and the next retry. The cached resource still contains the old
        # wrappers, but passing one of those wrappers into a new kernel would
        # raise ``StructRNA of type Image has been removed`` and strand the
        # owner in its error output. Treat an invalid pair as a fresh bank
        # allocation and let the normal ownership scan reclaim survivors.
        if banks is not None and parameter_bank_pair_images(banks) is None:
            resource.banks = None
            resource.active_bank = None
            resource.generation = None
            resource.trees.clear()
            banks = None
        fresh = banks is None
        if fresh:
            allocated = []
            try:
                primaries = []
                for bank in (0, 1):
                    role_images = {}
                    for role in PARAMETER_ROLES:
                        image = make_image(bank, role)
                        allocated.append(image)
                        role_images[role] = image
                        if not pack_role(image, role, parameters.roles[role],
                                         content_signatures[role]):
                            for allocated_image in allocated:
                                if allocated_image.users == 0:
                                    operations.bpy.data.images.remove(
                                        allocated_image, do_unlink=True)
                            return {"clean": False}
                    primaries.append(bind_parameter_bank(role_images))
                banks = tuple(primaries)
                for primary in banks:
                    primary[PARAMETER_SIGNATURE] = preparation_signature
                resources.set_banks(resource, banks, old_active, old_generation)
            except BaseException:
                for image in allocated:
                    if image.users == 0:
                        operations.bpy.data.images.remove(image, do_unlink=True)
                raise
        elif repair:
            if (not pack_bank(banks[old_active], parameters, content_signatures,
                              preparation_signature, force=True)
                    or not pack_bank(banks[candidate_bank], parameters,
                                     content_signatures, preparation_signature,
                                     force=True)):
                return {"clean": False}
        elif not pack_bank(banks[candidate_bank], parameters, content_signatures,
                           preparation_signature):
            return {"clean": False}

        kernels = dict(resource.trees)
        owner, owner_node = resources.owner(users[0]["node"])
        tree_types = set(kernels) | {
            record["node"].id_data.bl_idname for record in users
        }
        for tree_type in tree_types:
            kernel = kernels.get(tree_type)
            structure_valid = operations.parameter_kernel_structure_valid(kernel)
            if not structure_valid:
                kernel = operations.build_kernel(
                    tree_type, prepared, prepared.space,
                    operations.signature(tree_type, values, prepared.space),
                    banks, old_active, old_generation,
                )
                created.append(kernel)
                kernel[PARAMETER_OWNER] = owner
                if owner_node is not None:
                    kernel[PARAMETER_OWNER_NODE] = owner_node
                kernels[tree_type] = kernel
                structure_valid = operations.parameter_kernel_structure_valid(kernel)
            if not structure_valid:
                return {"clean": False}
            kernel[PARAMETER_ACTIVE_BANK] = old_active
            kernel[PARAMETER_GENERATION] = old_generation
            kernel[PARAMETER_SIGNATURE] = banks[old_active].get(PARAMETER_SIGNATURE)
        transaction.kernels = kernels
        transaction.metadata_before = tuple(
            (kernel, key, kernel.get(key))
            for kernel in kernels.values()
            for key in (PARAMETER_ACTIVE_BANK, PARAMETER_GENERATION,
                        PARAMETER_SIGNATURE, operations.kernel_signature_key)
        )
        verified_banks = banks if fresh or repair else (banks[candidate_bank],)
        return {"clean": all(
            operations.parameter_role_receipt_matches(image, role, content_signatures[role])
            for primary in verified_banks
            for role, image in parameter_bank_images(primary).items()
        ) and all(
            primary.get(PARAMETER_SIGNATURE) == preparation_signature
            and parameter_bundle_receipt_matches(primary)
            for primary in verified_banks
        )}

    def select(bank, _errors):
        kernels = transaction.kernels
        for kernel in kernels.values():
            operations.set_parameter_selector(kernel, bank)
            kernel[PARAMETER_ACTIVE_BANK] = bank
            kernel[PARAMETER_GENERATION] = generation
            kernel[PARAMETER_SIGNATURE] = preparation_signature
            tree_type = kernel.bl_idname
            kernel[operations.kernel_signature_key] = operations.signature(
                tree_type, values, prepared.space,
            )
        for node, _previous in transaction.outer_before:
            kernel = kernels[node.id_data.bl_idname]
            if operations.kernel_for_node(node) != kernel:
                operations.replace_node_kernel(node, kernel)
        selected = {operations.read_parameter_selector(kernel)
                    for kernel in kernels.values()}
        if selected != {bank} or any(
                kernel.get(PARAMETER_ACTIVE_BANK) != bank
                or kernel.get(PARAMETER_GENERATION) != generation
                or kernel.get(PARAMETER_SIGNATURE) != preparation_signature
                or kernel.get(PARAMETER_SIGNATURE)
                != kernel.get(PARAMETER_BANK_BINDINGS[bank]).get(PARAMETER_SIGNATURE)
                or kernel.get(operations.kernel_signature_key) != operations.signature(
                    kernel.bl_idname, values, prepared.space)
                for kernel in kernels.values()):
            raise RuntimeError("Grade parameter selector readback did not match the staged bank")
        return {"selected_bank": selected.pop()}

    def deliver(candidate_bank, _errors):
        resources.publish(resource, candidate_bank, generation)
        resource.trees = transaction.kernels
        active_images = parameter_bank_images(resource.image)
        for role in PARAMETER_ROLES:
            operations.invalidate_grade_parameters(active_images[role])
        transaction.receipt_before = operations.record_compositor_bindings(users)
        delivery_errors = []
        for record in users:
            event_kind = ("recovery_result" if record["state"].error is not None
                          else "installation_result")
            delivery_errors.extend(operations.dispatch(record["node"], node_policy.Event(
                event_kind,
                operations.signature(record["node"].id_data.bl_idname,
                                     values, prepared.space),
                playback_preview=operations.playback_preview(record, playback_session),
            ), recovery=recovery))
        if delivery_errors:
            raise ExceptionGroup("Grade installation delivery failed", delivery_errors)
        operations.tag_compositor_outputs(users)
        return {"delivered": True}

    def restore_selector(bank, _errors):
        restoration_errors = []
        kernels = transaction.kernels.values()
        for kernel in kernels:
            try:
                operations.set_parameter_selector(kernel, bank)
                for key, value in ((PARAMETER_ACTIVE_BANK, old_active),
                                   (PARAMETER_GENERATION, old_generation)):
                    write_metadata(((kernel, key, value),))
            except Exception as error:
                restoration_errors.append(error)
        for node, previous in transaction.outer_before:
            try:
                if operations.kernel_for_node(node) != previous:
                    operations.replace_node_kernel(node, previous)
            except Exception as error:
                restoration_errors.append(error)
        for entry in transaction.metadata_before:
            try:
                write_metadata((entry,))
            except Exception as error:
                restoration_errors.append(error)
        try:
            resources.restore(resource, old_active, old_generation)
            resource.trees = transaction.previous_trees
        except Exception as error:
            restoration_errors.append(error)
        if transaction.receipt_before is not None:
            try:
                operations.restore_compositor_bindings(transaction.receipt_before)
            except Exception as error:
                restoration_errors.append(error)
        selected = set()
        for kernel in kernels:
            try:
                selected.add(operations.read_parameter_selector(kernel))
            except Exception as error:
                restoration_errors.append(error)
        if selected != {bank}:
            restoration_errors.append(RuntimeError(
                f"Grade bank selector restoration readback did not match bank {bank}"
            ))
        if restoration_errors:
            raise ExceptionGroup("Grade bank selector restoration failed", restoration_errors)
        return {"selected_bank": selected.pop()}

    def fail_closed(_bank, errors):
        error = errors[0] if errors else RuntimeError("Grade bank publication failed")
        affected = tuple(record for record in operations.node_stores.values()
                         if record.get("source") is source)
        installation_errors = []
        for record in affected or users:
            try:
                pointer = record["node"].as_pointer()
                if (not pointer
                        or operations.node_stores.get(pointer) is not record
                        or not operations.lifecycle.admits(recovery, pointer)):
                    continue
                installation_errors.extend(operations.fail_installation(
                    (record,), None, error, recovery=recovery))
            except Exception as failure:
                installation_errors.append(failure)
        if installation_errors:
            resource.trees = (transaction.kernels if transaction.kernels is not None
                              else transaction.previous_trees)
            raise ExceptionGroup("Could not establish the Grade error output",
                                 installation_errors)
        resource.trees = {}
        return {"closed": True}

    publication = run_bank_publication(
        old_active,
        {
            "stage": stage,
            "repair": lambda bank, errors: stage(bank, errors, repair=True),
            "select": select,
            "deliver": deliver,
            "restore_selector": restore_selector,
            "fail_closed": fail_closed,
        },
        admitted=admitted,
        active_valid=active_valid,
    )
    transaction_errors = list(publication.errors)
    if publication.outcome == "committed":
        previous = [
            tree for node, tree in transaction.outer_before
            if tree != transaction.kernels.get(node.id_data.bl_idname)
        ]
        previous.extend(
            tree for kind, tree in transaction.previous_trees.items()
            if tree != transaction.kernels.get(kind)
        )
        errors = list(operations.retire_kernels(tuple(previous))) if previous else []
        errors.extend(resources.reclaim(resource, operations.remove_parameter_image))
        transaction_errors.extend(errors)
    elif publication.outcome == "failed_closed":
        if not transaction_errors:
            transaction_errors.append(RuntimeError(
                "Grade bank publication ended " + publication.outcome
            ))
        previous = tuple(tree for _node, tree in transaction.outer_before)
        errors = list(operations.retire_kernels(tuple((*created, *previous))))
        errors.extend(resources.reclaim(resource, operations.remove_parameter_image))
        transaction_errors.extend(errors)
    else:
        resource.trees = (transaction.kernels if transaction.kernels is not None
                          else transaction.previous_trees)
        transaction_errors.append(RuntimeError(
            "Grade bank publication could not establish a reliable output"
        ))

    diagnostic_nodes = []
    for record in tuple(operations.node_stores.values()):
        if record.get("source") != source:
            continue
        try:
            if record["node"].as_pointer():
                diagnostic_nodes.append(record["node"])
        except ReferenceError:
            continue
    failures = []
    for error in transaction_errors:
        failures.append((tuple(diagnostic_nodes), error))
        message = "recovered during" if publication.outcome == "committed" else "failed during"
        print(f"Perceptual Grade bank publication {message} publication:", error)
    return tuple(failures)
