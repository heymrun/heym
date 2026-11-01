"""Fixed limits of the file-analysis sandbox.

Constants rather than settings: they are properties of the sandbox, not
deployment configuration.
"""

MEMORY_LIMIT = "2g"
CPU_LIMIT = "2"
PIDS_LIMIT = "256"
CALL_TIMEOUT_SECONDS = 120.0
TMPFS = "/tmp:rw,nosuid,size=512m"

# Inputs and scratch together, per workspace.
MAX_WORKSPACE_BYTES = 2 * 1024**3
MAX_OUTPUT_FILES = 20
MAX_OUTPUT_FILE_BYTES = 100 * 1024**2
MAX_STDOUT_CHARS = 20_000
MAX_CODE_CHARS = 100_000
MAX_FILES_PER_CALL = 20

# Sandbox containers running at once on one instance.
MAX_CONCURRENT_CONTAINERS = 4

CHAT_WORKSPACE_IDLE_DAYS = 30
CHAT_WORKSPACE_SWEEP_INTERVAL_SECONDS = 6 * 3600

LIST_FILES_DEFAULT_LIMIT = 50
LIST_FILES_MAX_LIMIT = 200
