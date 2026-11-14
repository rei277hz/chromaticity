"""Runtime metadata keys for template-backed Stage 2 kernels.

The graph emitter owns the topology; these keys are the small persistent
contract needed by publication and recovery after the emitter leaves the
installed extension.
"""

PARAMETER_IMAGE = "_perceptual_grade_parameter_schema"
PARAMETER_BANK_BINDINGS = (
    "_perceptual_grade_parameter_bank_0",
    "_perceptual_grade_parameter_bank_1",
)
PARAMETER_BINDING = PARAMETER_BANK_BINDINGS[0]
PARAMETER_ACTIVE_BANK = "_perceptual_grade_parameter_active_bank"
PARAMETER_GENERATION = "_perceptual_grade_parameter_generation"
PARAMETER_SELECTOR = "_perceptual_grade_parameter_selector"
PARAMETER_SAMPLE_SELECTOR = "_perceptual_grade_parameter_sample_selector"
PARAMETER_SAMPLE_ID = "_perceptual_grade_parameter_sample_id"
PARAMETER_SAMPLE_KIND = "_perceptual_grade_parameter_sample_kind"
PARAMETER_SAMPLE_BANK = "_perceptual_grade_parameter_sample_bank"
PARAMETER_READER = "_perceptual_grade_parameter_reader"
PARAMETER_READER_BANK = "_perceptual_grade_parameter_reader_bank"

TEMPLATE_SCHEMA = "perceptual-grade-node-template-v1"
TEMPLATE_KIND = "_perceptual_grade_template_kind"
TEMPLATE_VARIANT = "_perceptual_grade_template_variant"
TEMPLATE_IMAGE_ROLE = "_perceptual_grade_template_image_role"
TEMPLATE_IMAGE_ROLE_BOUNDARY = "boundary"
TEMPLATE_IMAGE_ROLE_PARAMETER = "parameter"
TEMPLATE_IMAGE_ROLE_STACK = "stack_lut"

