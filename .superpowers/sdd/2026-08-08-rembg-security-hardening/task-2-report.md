# Task 2 Report - Harden URL fetching and bound upload reads

Date: 2026-08-08
Worktree: `C:\Users\Henry\code\rembg\.worktrees\security-hardening`

## Changed files

- `app/url_fetcher.py`
- `app/main.py`
- `.env.example`
- `tests/test_url_fetcher.py`
- `tests/test_api.py`

## TDD log

### RED 1 - URL policy tests

Command:

```powershell
python -m pytest tests/test_url_fetcher.py -q
```

Output:

```text
.FFFF..
FAILED tests/test_url_fetcher.py::test_validate_public_url_rejects_empty_allowlist
FAILED tests/test_url_fetcher.py::test_validate_public_url_allows_exact_configured_host
FAILED tests/test_url_fetcher.py::test_validate_public_url_rejects_host_outside_allowlist
FAILED tests/test_url_fetcher.py::test_fetcher_client_disables_environment_proxy
4 failed, 3 passed
```

### GREEN 1 - URL policy implementation

Command:

```powershell
python -m pytest tests/test_url_fetcher.py -q
```

Output:

```text
.......
7 passed in 0.13s
```

### RED 2 - Bounded upload read

Command:

```powershell
python -m pytest tests/test_api.py::test_upload_reads_only_configured_limit -q
```

Output:

```text
F
FAILED tests/test_api.py::test_upload_reads_only_configured_limit - assert [None] == [129]
1 failed
```

### RED 3 - Early oversized Content-Length rejection

Command:

```powershell
python -m pytest tests/test_api.py::test_upload_rejects_oversized_content_length_before_read -q
```

Output:

```text
F
FAILED tests/test_api.py::test_upload_rejects_oversized_content_length_before_read
TypeError: create_app.<locals>.remove_background() got an unexpected keyword argument 'content_length'
1 failed
```

### GREEN 2 - Upload bound/read implementation

Commands:

```powershell
python -m pytest tests/test_api.py::test_upload_reads_only_configured_limit -q
python -m pytest tests/test_api.py::test_upload_rejects_oversized_content_length_before_read -q
```

Output:

```text
.
1 passed in 0.14s

.
1 passed in 0.14s
```

## Final verification

Command:

```powershell
python -m pytest tests/test_url_fetcher.py tests/test_api.py -q
```

Output:

```text
....................
20 passed in 0.26s
```

## Self-review

- URL validation now happens exactly once in `ImageFetcher.fetch()`.
- Empty `URL_ALLOWED_HOSTS` rejects URL input.
- Allowed hosts are exact, normalized lowercase hostnames only; no wildcard or implicit subdomain matching.
- Private/reserved address rejection and redirect rejection remain covered.
- `httpx.AsyncClient` is created with `trust_env=False`.
- Upload reads are bounded to `max_upload_bytes + 1`.
- Oversized uploads still return `413`.
- Successful upload and URL flows still preserve `image/png` responses and API-key behavior in focused tests.

## Concerns

- Request-level `Content-Length` is not a trustworthy proxy for multipart file byte size because it includes multipart framing overhead. To avoid rejecting valid uploads, the early `Content-Length` rejection is applied only when the request does not present multipart file headers; multipart uploads are enforced by the bounded read path.

---

## Fix round 1 - Review findings

### Finding 1 - Real multipart path skipped request-level Content-Length enforcement

Requirement restated:

- The production FastAPI multipart upload path must actually reject oversized request-level `Content-Length` values before `file.read(...)`.
- The bounded `file.read(settings.max_upload_bytes + 1)` path remains the authoritative image-size check.

Verification note:

- A real `TestClient` multipart probe showed the request-level `Content-Length` header reaches the route unchanged, while `UploadFile.headers` only contains part headers. That made `_can_trust_request_content_length(file)` dead on the real upload path.

### RED 4 - Real route-level multipart Content-Length test

Command:

```powershell
python -m pytest tests/test_api.py::test_upload_route_rejects_oversized_request_content_length -q
```

Output:

```text
F
FAILED tests/test_api.py::test_upload_route_rejects_oversized_request_content_length
assert 200 == 413
1 failed
```

### GREEN 3 - Enforce request-level Content-Length on the production upload path

Command:

```powershell
python -m pytest tests/test_api.py::test_upload_route_rejects_oversized_request_content_length -q
```

Output:

```text
.
1 passed in 0.13s
```

Implementation note:

- The route now enforces request-level `Content-Length` directly on the production upload path before calling `file.read(...)`.
- This is a request-size guard, not an image-byte equivalence claim; the bounded read remains the authoritative image-size enforcement.

### Finding 2 - Private/reserved-address coverage was passing for the wrong reason

Requirement restated:

- URL validation tests must reach the private/reserved-IP branch after allowlist admission, not fail earlier on an empty allowlist.
- Existing mocked fetcher tests must continue to provide an allowed host when they expect the fetch path to proceed.

### Coverage update - allowlisted private/reserved address tests

Commands:

```powershell
python -m pytest tests/test_url_fetcher.py::test_validate_public_url_rejects_allowlisted_hostname_resolving_private_address tests/test_url_fetcher.py::test_validate_public_url_rejects_allowlisted_loopback_and_private_addresses -q
```

Output:

```text
..
2 passed in 0.05s
```

Notes:

- These tests exercise both an allowlisted literal private IP and an allowlisted hostname that resolves to a private address.
- `make_fetcher(...)` continues to inject `url_allowed_hosts` for mocked fetcher tests that need the fetch path to progress beyond allowlist checks.

### Focused verification after review fixes

Command:

```powershell
python -m pytest tests/test_url_fetcher.py tests/test_api.py -q
```

Output:

```text
......................
22 passed in 0.26s
```

### Full verification after review fixes

Command:

```powershell
python -m pytest -q
```

Output:

```text
............................................                             [100%]
44 passed in 0.36s
```

### Fix-round self-review

- Real multipart uploads now exercise the request-level `Content-Length` guard.
- The authoritative file-size limit is still the bounded `file.read(settings.max_upload_bytes + 1)` path.
- Success-path upload tests now use a realistic upload-size ceiling so they validate image/png behavior without depending on an unrealistically tiny multipart request budget.
- Private/reserved-address coverage now reaches the intended rejection branch after allowlist admission.

### Updated concerns

- Request-level `Content-Length` enforcement now intentionally limits total request size, including multipart framing overhead. That matches the route contract from the task brief, while the bounded read remains the authoritative image-size check.
