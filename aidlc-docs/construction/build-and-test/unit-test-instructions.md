# Unit Test Execution — Content Library Rework

## Run All Events Service Tests

```bash
python3 -m pytest services/events -q
```

**Expected**: 317 passed, 0 failed (verified during code generation)

### New test files introduced by this rework

| File | Tests | Coverage |
|---|---|---|
| `services/events/tests/test_library_service.py` | 40 | LibraryService: search, Path 1/2/3, curation, tags |
| `services/events/tests/test_library_consumers.py` | 5 | ContributionApprovedConsumer |
| `services/events/tests/test_event_complete_description.py` | 5 | Mandatory description on complete |

### Run only new Library tests

```bash
python3 -m pytest services/events/tests/test_library_service.py \
                  services/events/tests/test_library_consumers.py \
                  services/events/tests/test_event_complete_description.py -v
```

---

## Run All Contributions Service Tests

```bash
python3 -m pytest services/contributions-scoring -q
```

**Expected**: 67 passed, 0 failed (verified during code generation)

### New test file

| File | Tests | Coverage |
|---|---|---|
| `services/contributions-scoring/tests/test_submission_library_optin.py` | 5 | Library opt-in at approval |

### Run only new Contributions Library tests

```bash
python3 -m pytest services/contributions-scoring/tests/test_submission_library_optin.py -v
```

---

## Frontend Tests

```bash
cd frontend && npm test -- --run
```

**Expected**: existing tests pass; no new frontend unit tests added (UI components are tested via the existing test infrastructure).

---

## Key Test Scenarios Covered

### Business Rule Coverage

| Rule | Test |
|---|---|
| BR-LIB-S1 search-first | `test_search_first_no_filters_returns_empty` |
| BR-LIB-A1 Administrator excluded | `test_administrator_denied`, `test_administrator_denied_tags` |
| BR-LIB-A2 Members read-only | `test_member_cannot_add`, `test_member_cannot_edit`, `test_member_cannot_delete` |
| BR-LIB-A3 CL/UGL curate any resource | `test_cl_can_edit`, `test_ugl_can_edit_any_resource`, `test_ugl_can_delete_any_resource` |
| BR-LIB-P1 Path 1 scan trigger | `test_promote_event_materials_promotes_clean_uploaded` |
| BR-LIB-P4 Quarantined never promoted | `test_promote_skips_quarantined` |
| BR-LIB-P5 Auto-removal on material delete | `test_auto_removal_on_material_delete` |
| BR-LIB-P7 Path 2 EventBridge consumer | `test_add_to_library_true_creates_resource` |
| BR-LIB-P10 Points separate from Library | `test_points_awarded_still_published_regardless_of_library_opt_in` |
| BR-LIB-P12 Path 2 idempotency | `test_idempotent_via_idempotency_store`, `test_add_from_contribution_idempotent` |
| BR-LIB-V2 Mandatory description | `test_missing_description_rejected`, `test_complete_without_description_raises_validation_error` |
| BR-LIB-V5 URL must be https | `test_link_without_https_rejected` |
| BR-LIB-T1 Lowercase tag normalization | `test_add_updates_tag_registry` |
| US-2.19 Mandatory description on complete | `TestMandatoryDescriptionOnComplete` class |
