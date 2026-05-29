# Example 1 — PyPI dependency audit (Investigate / Decide mode)

**Question:** What are the dependencies of `httpx` 0.27.0, and are any of
them outdated or potentially vulnerable?

**Tool sequence:**
```python
# Step 1: Get package metadata
meta = run(ctx, "pypi:httpx")  # latest version + license

# Step 2: Get dependencies for a specific version
deps = pypi_get_dependencies("httpx", version="0.27.0")
# Each Document: metadata["dependency_spec"] e.g. "certifi; python_version >= '3.8'"

# Step 3: For each direct dep, get latest version
for dep_spec in [d.metadata["dependency_spec"] for d in deps]:
    dep_name = dep_spec.split(";")[0].split(" ")[0].split(">=")[0].strip()
    latest = pypi_fetch_package_metadata(dep_name)
    # compare latest version vs what's in the dep spec
```

**Expected output shape:**
- 1 package Document for httpx: `metadata["version"]`, `metadata["license"]`
- N dependency Documents: `metadata["dependency_spec"]`, `metadata["package"]`
- 1 package Document per dep: current latest version for comparison

**Output guidance:**
Produce a table: dependency | required spec | current latest | outdated?.
Flag any dep where the spec allows versions older than current latest by more
than one minor version.
