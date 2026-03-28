#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${ROOT_DIR}/diagrams"
TMP_DIR="${OUTPUT_DIR}/.tmp"
PROJECT_NAME="terrain_layers"
SOURCE_DIRS=(
  "${ROOT_DIR}/config"
  "${ROOT_DIR}/masks"
  "${ROOT_DIR}/shader"
  "${ROOT_DIR}/utility"
  "${ROOT_DIR}/biomes"
)
PYDEPS_TARGET="${ROOT_DIR}/pipeline.py"

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

PYREVERSE="$(resolve_cmd pyreverse)" || {
  echo "Missing required command: pyreverse"
  exit 1
}
PYDEPS="$(resolve_cmd pydeps)" || {
  echo "Missing required command: pydeps"
  exit 1
}
DOT="$(resolve_cmd dot)" || {
  echo "Missing required command: dot"
  echo "Install Graphviz so DOT files can be rendered to SVG."
  exit 1
}

mkdir -p "${OUTPUT_DIR}" "${TMP_DIR}"

mapfile -t PYREVERSE_TARGETS < <(
  find "${SOURCE_DIRS[@]}" -type f -name '*.py' ! -path '*/__pycache__/*' | sort
)
PYREVERSE_TARGETS+=("${ROOT_DIR}/pipeline.py")

export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

echo "Generating UML/package diagrams with pyreverse..."
pushd "${TMP_DIR}" >/dev/null
"${PYREVERSE}" -o dot -p "${PROJECT_NAME}" "${PYREVERSE_TARGETS[@]}"
if [[ -f "classes_${PROJECT_NAME}.dot" ]]; then
  "${DOT}" -Tsvg "classes_${PROJECT_NAME}.dot" -o "${OUTPUT_DIR}/classes_${PROJECT_NAME}.svg"
fi
if [[ -f "packages_${PROJECT_NAME}.dot" ]]; then
  "${DOT}" -Tsvg "packages_${PROJECT_NAME}.dot" -o "${OUTPUT_DIR}/packages_${PROJECT_NAME}.svg"
fi
popd >/dev/null

echo "Generating import dependency graph with pydeps..."
pushd "${ROOT_DIR}" >/dev/null
"${PYDEPS}" "${PYDEPS_TARGET}" \
  --cluster \
  --max-bacon 2 \
  --no-show \
  -T svg \
  -o "${OUTPUT_DIR}/${PROJECT_NAME}_imports.svg"
popd >/dev/null

rm -f "${TMP_DIR}"/*.dot
rmdir "${TMP_DIR}" 2>/dev/null || true

echo
echo "Diagrams written to:"
echo "  ${OUTPUT_DIR}/classes_${PROJECT_NAME}.svg"
echo "  ${OUTPUT_DIR}/packages_${PROJECT_NAME}.svg"
echo "  ${OUTPUT_DIR}/${PROJECT_NAME}_imports.svg"
