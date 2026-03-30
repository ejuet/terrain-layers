#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${ROOT_DIR}/diagrams"
TMP_DIR="${OUTPUT_DIR}/.tmp"
PROJECT_NAME="terrain_layers"
PACKAGE_DIR="${ROOT_DIR}/terrain_layers"
SOURCE_DIRS=(
  "${PACKAGE_DIR}/config"
  "${PACKAGE_DIR}/masks"
  "${PACKAGE_DIR}/shader"
  "${PACKAGE_DIR}/utility"
  "${PACKAGE_DIR}/biomes"
  "${PACKAGE_DIR}/paths"
  "${PACKAGE_DIR}/preview_shader"
)
PYDEPS_TARGET="${PACKAGE_DIR}/pipeline.py"

if [[ -d "${ROOT_DIR}/venv" ]]; then
  # Use the repo-local virtual environment when present.
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/venv/bin/activate"
fi

resolve_cmd() {
  local name="$1"
  if command -v "${name}" >/dev/null 2>&1; then
    command -v "${name}"
    return 0
  fi
  return 1
}

warn_missing() {
  local name="$1"
  echo "Skipping ${name}: command not found."
}

DOT="$(resolve_cmd dot)" || {
  echo "Missing required command: dot"
  echo "Install Graphviz so DOT files can be rendered to SVG."
  exit 1
}
PYREVERSE="$(resolve_cmd pyreverse || true)"
PYDEPS="$(resolve_cmd pydeps || true)"

mkdir -p "${OUTPUT_DIR}" "${TMP_DIR}"

mapfile -t PYREVERSE_TARGETS < <(
  find "${SOURCE_DIRS[@]}" -type f -name '*.py' ! -path '*/__pycache__/*' | sort
)
PYREVERSE_TARGETS+=("${PACKAGE_DIR}/pipeline.py")

export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

echo "Generating grouped package dependency diagram..."
PACKAGE_DOT="${TMP_DIR}/packages_${PROJECT_NAME}.dot"
python "${ROOT_DIR}/generate_package_diagram.py" "${ROOT_DIR}" "${PROJECT_NAME}" "${PACKAGE_DOT}"
"${DOT}" -Tsvg "${PACKAGE_DOT}" -o "${OUTPUT_DIR}/packages_${PROJECT_NAME}.svg"
GENERATED_DIAGRAMS=("${OUTPUT_DIR}/packages_${PROJECT_NAME}.svg")

if [[ -n "${PYREVERSE}" ]]; then
  echo "Generating class diagram with pyreverse..."
  pushd "${TMP_DIR}" >/dev/null
  "${PYREVERSE}" -o dot -p "${PROJECT_NAME}" "${PYREVERSE_TARGETS[@]}"
  if [[ -f "classes_${PROJECT_NAME}.dot" ]]; then
    "${DOT}" -Tsvg "classes_${PROJECT_NAME}.dot" -o "${OUTPUT_DIR}/classes_${PROJECT_NAME}.svg"
    GENERATED_DIAGRAMS+=("${OUTPUT_DIR}/classes_${PROJECT_NAME}.svg")
  fi
  popd >/dev/null
else
  warn_missing "class diagram (pyreverse)"
fi

if [[ -n "${PYDEPS}" ]]; then
  echo "Generating import dependency graph with pydeps..."
  pushd "${ROOT_DIR}" >/dev/null
  "${PYDEPS}" "${PYDEPS_TARGET}" \
    --cluster \
    --max-bacon 2 \
    --no-show \
    -T svg \
    -o "${OUTPUT_DIR}/${PROJECT_NAME}_imports.svg"
  GENERATED_DIAGRAMS+=("${OUTPUT_DIR}/${PROJECT_NAME}_imports.svg")
  popd >/dev/null
else
  warn_missing "import dependency graph (pydeps)"
fi

rm -f "${TMP_DIR}"/*.dot
rmdir "${TMP_DIR}" 2>/dev/null || true

echo
echo "Diagrams written to:"
for diagram in "${GENERATED_DIAGRAMS[@]}"; do
  echo "  ${diagram}"
done
