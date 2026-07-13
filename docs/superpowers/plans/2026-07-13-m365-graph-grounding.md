# M365 Graph Grounding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the proxy answer questions grounded in the user's Microsoft 365 data by connecting to substrate as the paid Copilot scenario.

**Architecture:** Make the substrate `scenario` and `license_type` configurable (defaulting to the paid/premium values that unlock Graph grounding), plumbed from `Settings` through the client factory into `SubstrateCopilotClient._ws_url`. No new endpoints; grounding becomes available on every request.

**Tech Stack:** Python 3.11+, Pydantic Settings, pytest. No new dependencies.

## Global Constraints

- Python `>=3.11`; no new runtime dependencies.
- Validated enabling values (verified live): `scenario=OfficeWebPaidCopilot`, `licenseType=Premium`. Use these exact strings as defaults.
- Keep `SubstrateCopilotClient(access_token, time_zone)` positional compatibility — add `scenario`/`license_type` as keyword parameters after `time_zone`.
- Run tests with: `uv run --extra dev pytest <path> -v` from the repo root.
- Commit after each task with the message shown in that task's final step.

---

## File Structure

- Modify: `src/m365_copilot_openai_proxy/config.py` — add `scenario` and `license_type` settings.
- Modify: `src/m365_copilot_openai_proxy/substrate_client.py` — accept `scenario`/`license_type`, use them in `_ws_url`.
- Modify: `src/m365_copilot_openai_proxy/app.py` — factory passes the settings through.
- Modify: `tests/test_app.py` — unit tests for `_ws_url` values and factory plumbing.

---

## Task 1: Configurable scenario and license_type

**Files:**
- Modify: `src/m365_copilot_openai_proxy/config.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Produces: `Settings.scenario: str` (default `"OfficeWebPaidCopilot"`, alias `M365_SCENARIO`) and `Settings.license_type: str` (default `"Premium"`, alias `M365_LICENSE_TYPE`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
def test_settings_default_to_paid_grounding_scenario() -> None:
    settings = Settings(M365_ACCESS_TOKEN="x")
    assert settings.scenario == "OfficeWebPaidCopilot"
    assert settings.license_type == "Premium"


def test_settings_scenario_and_license_are_overridable() -> None:
    settings = Settings(
        M365_ACCESS_TOKEN="x",
        M365_SCENARIO="OfficeWebIncludedCopilot",
        M365_LICENSE_TYPE="Starter",
    )
    assert settings.scenario == "OfficeWebIncludedCopilot"
    assert settings.license_type == "Starter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_app.py::test_settings_default_to_paid_grounding_scenario -v`
Expected: FAIL (`Settings` has no `scenario` attribute).

- [ ] **Step 3: Write minimal implementation**

In `src/m365_copilot_openai_proxy/config.py`, add two fields to `Settings` after `model_alias`:

```python
    scenario: str = Field(default="OfficeWebPaidCopilot", alias="M365_SCENARIO")
    license_type: str = Field(default="Premium", alias="M365_LICENSE_TYPE")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_app.py -k "scenario or license" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/m365_copilot_openai_proxy/config.py tests/test_app.py
git commit -m "feat: add configurable substrate scenario and license_type"
```

---

## Task 2: Use scenario/license_type in the substrate WebSocket URL

**Files:**
- Modify: `src/m365_copilot_openai_proxy/substrate_client.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SubstrateCopilotClient(access_token, time_zone="Asia/Tokyo", scenario="OfficeWebPaidCopilot", license_type="Premium")`; `_ws_url` interpolates `self._scenario` and `self._license_type`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py` (reuses the module-level `make_jwt` helper):

```python
def test_ws_url_defaults_to_paid_grounding_params() -> None:
    client = SubstrateCopilotClient(make_jwt(int(time.time()) + 3600))
    url = client._ws_url("conv", "sess", "req")
    assert "scenario=OfficeWebPaidCopilot" in url
    assert "licenseType=Premium" in url
    assert "OfficeWebIncludedCopilot" not in url
    assert "licenseType=Starter" not in url


def test_ws_url_honors_custom_scenario_and_license() -> None:
    client = SubstrateCopilotClient(
        make_jwt(int(time.time()) + 3600),
        scenario="OfficeWebIncludedCopilot",
        license_type="Starter",
    )
    url = client._ws_url("conv", "sess", "req")
    assert "scenario=OfficeWebIncludedCopilot" in url
    assert "licenseType=Starter" in url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_app.py::test_ws_url_defaults_to_paid_grounding_params -v`
Expected: FAIL (URL still contains `OfficeWebIncludedCopilot` / `licenseType=Starter`).

- [ ] **Step 3: Write minimal implementation**

In `src/m365_copilot_openai_proxy/substrate_client.py`, change the `__init__` signature and store the new values. Replace:

```python
    def __init__(self, access_token: str, time_zone: str = "Asia/Tokyo"):
```

with:

```python
    def __init__(
        self,
        access_token: str,
        time_zone: str = "Asia/Tokyo",
        scenario: str = "OfficeWebPaidCopilot",
        license_type: str = "Premium",
    ):
```

Immediately after `self._time_zone = time_zone`, add:

```python
        self._scenario = scenario
        self._license_type = license_type
```

Then change the final line of the returned URL in `_ws_url` from:

```python
            f"&licenseType=Starter&agent=web&scenario=OfficeWebIncludedCopilot"
```

to:

```python
            f"&licenseType={self._license_type}&agent=web&scenario={self._scenario}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_app.py -k "ws_url" -v`
Expected: PASS

- [ ] **Step 5: Run the full suite (no regression)**

Run: `uv run --extra dev pytest -v`
Expected: PASS (existing substrate/token tests still green — the constructor change is backward compatible).

- [ ] **Step 6: Commit**

```bash
git add src/m365_copilot_openai_proxy/substrate_client.py tests/test_app.py
git commit -m "feat: connect to substrate as the configured Copilot scenario"
```

---

## Task 3: Plumb settings through the client factory

**Files:**
- Modify: `src/m365_copilot_openai_proxy/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `Settings.scenario`, `Settings.license_type`; `SubstrateCopilotClient(..., scenario=..., license_type=...)`.
- Produces: the default `copilot_client_factory` constructs the client with the settings' scenario and license.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
def test_factory_passes_scenario_and_license_to_client(tmp_path, monkeypatch) -> None:
    token = make_jwt(int(time.time()) + 3600)
    env_path = tmp_path / ".env"
    env_path.write_text(f"M365_ACCESS_TOKEN={token}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    seen: dict = {}

    class RecordingCopilotClient(FakeCopilotClient):
        def __init__(self, access_token, time_zone, scenario, license_type):
            super().__init__()
            seen["scenario"] = scenario
            seen["license_type"] = license_type

    monkeypatch.setattr(
        "m365_copilot_openai_proxy.app.SubstrateCopilotClient",
        RecordingCopilotClient,
    )
    settings = Settings(
        M365_ACCESS_TOKEN=token,
        M365_SCENARIO="OfficeWebPaidCopilot",
        M365_LICENSE_TYPE="Premium",
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "ignored", "messages": [{"role": "user", "content": "Hello"}]},
    )

    assert response.status_code == 200
    assert seen == {"scenario": "OfficeWebPaidCopilot", "license_type": "Premium"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_app.py::test_factory_passes_scenario_and_license_to_client -v`
Expected: FAIL (`RecordingCopilotClient.__init__` gets no `scenario`/`license_type` — the factory doesn't pass them).

- [ ] **Step 3: Write minimal implementation**

In `src/m365_copilot_openai_proxy/app.py`, change the default factory from:

```python
    app.state.copilot_client_factory = copilot_client_factory or (
        lambda: SubstrateCopilotClient(app.state.token_store.get(), resolved_settings.time_zone)
    )
```

to:

```python
    app.state.copilot_client_factory = copilot_client_factory or (
        lambda: SubstrateCopilotClient(
            app.state.token_store.get(),
            resolved_settings.time_zone,
            scenario=resolved_settings.scenario,
            license_type=resolved_settings.license_type,
        )
    )
```

Then fix the pre-existing test that stubs the client constructor — the factory now
passes `scenario`/`license_type` kwargs, so its stub must accept them. In
`tests/test_app.py`, inside `test_default_client_factory_reloads_token_from_env`,
change the `RecordingCopilotClient.__init__` signature from:

```python
        def __init__(self, access_token: str, _time_zone: str):
```

to:

```python
        def __init__(self, access_token: str, _time_zone: str, scenario: str = "", license_type: str = ""):
```

(The body is unchanged — it still only appends `access_token` to `seen_tokens`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_app.py::test_factory_passes_scenario_and_license_to_client -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/m365_copilot_openai_proxy/app.py tests/test_app.py
git commit -m "feat: build the Copilot client with the configured scenario and license"
```

---

## Task 4: Live grounding verification and README note

**Files:**
- Modify: `README.md`

**Interfaces:** none (manual verification + docs).

- [ ] **Step 1: Restart the proxy on this branch's code and confirm health**

Ensure the running proxy uses this branch's code and has a valid token, then:
Run (PowerShell): `Invoke-RestMethod http://127.0.0.1:8000/v1/token/status`
Expected: `valid: True`.

- [ ] **Step 2: Confirm grounding works end to end**

Send a grounded query and confirm it returns real data rather than a refusal:
```powershell
$body = @{ model = "m365-copilot"; messages = @(@{ role = "user"; content = "Do I have any meetings on my calendar today? Reply with only a number." }) } | ConvertTo-Json -Depth 10
(Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/chat/completions" -ContentType "application/json" -Body $body).choices[0].message.content
```
Expected: a number (grounded answer), NOT "I can't access your calendar."

- [ ] **Step 3: Update the README**

In `README.md`, under "Environment Variables", add rows for `M365_SCENARIO` (default `OfficeWebPaidCopilot`) and `M365_LICENSE_TYPE` (default `Premium`), noting they select the paid Copilot scenario that grounds in the user's M365 data, and that accounts without a paid M365 Copilot license should set them to `OfficeWebIncludedCopilot` / `Starter`. Add a short "Querying your M365 data" note that grounded natural-language queries (mail, calendar, files) work by default and require a paid M365 Copilot license.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document M365 data grounding and scenario/license settings"
```

---

## Self-Review Notes

- **Spec coverage:** config settings (Task 1), `_ws_url` uses them (Task 2), factory plumbing (Task 3), verification + docs (Task 4). All spec components mapped.
- **Type consistency:** `scenario` / `license_type` are `str` everywhere; constructor keyword order (`access_token, time_zone, scenario, license_type`) matches the factory call and the Task 3 test's `RecordingCopilotClient.__init__`.
- **No placeholders:** every code step contains the exact code; test assertions are concrete.
