## 2026-04-21
- `HostSnapshot.from_json()` must rebuild nested `OpenCodeSession` and `OpenCodeBurst` objects, or roundtrip equality fails.
- Keeping `schema_version` as the last dataclass field avoids default-before-non-default ordering issues.
- Validation stayed intentionally narrow: required host label, host platform, and YYYY-MM-DD date only.
