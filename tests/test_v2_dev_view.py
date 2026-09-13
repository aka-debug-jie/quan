"""Offline synthetic trust, scope and minimal-projection regressions."""

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from quant_stack_v2.dev_contract import (
    DevContract,
    DevEvidence,
    FeatureSpec,
    LabelSpec,
    Member,
    ModelSpec,
    Row,
    SourcePacket,
    Span,
    UsePins,
    attest_synthetic,
    canonical,
    digest,
    load_contract,
    load_evidence,
    read_blob,
    tree_identity,
    write_blob,
)
from quant_stack_v2.dev_view import dependency_sessions, export_view, load_view, sample_sessions


def make_fixture(tmp_path: Path) -> tuple[Path, Path, Path, UsePins, str]:
    """Construct an entire approved synthetic scope from temporary bytes only."""
    authority, source_root, view_root = (tmp_path / n for n in ("authority", "source", "view"))
    days = tuple(date(2000, 1, 1) + timedelta(days=i) for i in range(72))
    symbols = ("SYNTH_A", "SYNTH_B")
    members = tuple(Member(symbol=s, start=days[0], end=days[-1]) for s in (*symbols, "SYNTH_OUT"))
    rows = tuple(
        Row(
            symbol=s,
            session=d,
            values={
                "close": 100 + 0.3 * i + (i % 5) * 0.4 + j,
                "volume": 1000 + (i * 17 + j) % 41,
                "unapproved": 12345,
            },
        )
        for j, s in enumerate((*symbols, "SYNTH_OUT"))
        for i, d in enumerate(days)
    )
    source = SourcePacket(
        schema_version=1,
        data_kind="SYNTHETIC",
        universe="csi300",
        provider_id="synthetic_fixture",
        price_semantics="SYNTHETIC_POSITIVE_LEVELS",
        sessions=days,
        fields=("close", "volume", "unapproved"),
        members=members,
        rows=rows,
    )
    source_sha = write_blob(source_root, canonical(source))
    contract = DevContract(
        schema_version=1,
        usage="LIMITED_DEV_RESEARCH",
        run_kind="DEV_SMOKE",
        data_kind="SYNTHETIC",
        universe="csi300",
        formal_qualification="BLOCKED_DATA",
        sealed_test="NOT_STARTED",
        snapshot_sha256=source_sha,
        tree_sha256=tree_identity(source_sha),
        source_sha256=source_sha,
        price_semantics="SYNTHETIC_POSITIVE_LEVELS",
        symbols=symbols,
        fields=("close", "volume"),
        sessions=days,
        source=Span(start=days[0], end=days[-1]),
        train=Span(start=days[3], end=days[39]),
        valid=Span(start=days[44], end=days[69]),
        warmup_sessions=1,
        train_label_end=days[41],
        valid_label_end=days[71],
        embargo_sessions=2,
        features=(
            FeatureSpec(name="close_now", field="close", lag=0),
            FeatureSpec(name="volume_lag", field="volume", lag=1),
        ),
        label=LabelSpec(kind="forward_ratio", field="close", start_offset=1, end_offset=2),
        preprocessing="train_standardize_complete_cases",
        models=(
            ModelSpec(kind="linear", seed=1701, params={"fit_intercept": True}),
            ModelSpec(
                kind="lightgbm",
                seed=1701,
                params={
                    "n_estimators": 20,
                    "num_leaves": 7,
                    "learning_rate": 0.1,
                    "min_child_samples": 5,
                    "max_depth": 3,
                },
            ),
        ),
    )
    csha = write_blob(authority, canonical(contract))
    esha = attest_synthetic(source_root, authority, csha)
    pins = UsePins(csha, esha)
    view_sha = export_view(source_root, authority, view_root, pins)
    return (
        authority,
        source_root,
        view_root,
        UsePins(csha, esha, view_sha),
        view_sha,
    )


def test_projection_is_minimal_and_repeatable(tmp_path: Path) -> None:
    authority, source, views, pins, vsha = make_fixture(tmp_path)
    view = load_view(authority, views, pins, vsha)
    assert export_view(source, authority, views, pins) == vsha
    assert {r.symbol for r in view.data.rows} == set(view.contract.symbols)
    assert all(set(r.values) == {"close", "volume"} for r in view.data.rows)
    assert {r.session for r in view.data.rows} == set(dependency_sessions(view.contract))
    assert view.contract.sessions[2] not in sample_sessions(view.contract)
    assert view.contract.sessions[2] in dependency_sessions(view.contract)
    assert view.contract.sessions[0] not in dependency_sessions(view.contract)
    assert (
        view.contract.formal_qualification == "BLOCKED_DATA"
        and view.contract.sealed_test == "NOT_STARTED"
    )


def test_fake_qualification_does_not_supply_evidence(tmp_path: Path) -> None:
    authority, _, _, pins, _ = make_fixture(tmp_path)
    fake = write_blob(authority, canonical({"status": "QUALIFIED"}))
    with pytest.raises(ValueError):
        load_evidence(authority, UsePins(pins.contract_sha256, fake))
    with pytest.raises(FileNotFoundError):
        load_evidence(authority, UsePins(pins.contract_sha256, "0" * 64))


@pytest.mark.parametrize(
    "change",
    [
        {"snapshot_sha256": "0" * 64},
        {"tree_sha256": "0" * 64},
        {"source_sha256": "0" * 64},
        {"symbols": ["SYNTH_OUT"]},
        {"fields": ["close"]},
        {"source": {"start": "2000-01-02", "end": "2000-03-12"}},
        {"validator_version": "unreviewed-v9"},
    ],
)
def test_valid_json_wrong_identity_or_scope(tmp_path: Path, change: dict[str, object]) -> None:
    authority, _, _, pins, _ = make_fixture(tmp_path)
    body = json.loads(read_blob(authority, pins.evidence_sha256))
    body.update(change)
    fake = write_blob(authority, canonical(body))
    with pytest.raises(ValueError):
        load_evidence(authority, UsePins(pins.contract_sha256, fake))


def test_source_drift_rejected_before_export(tmp_path: Path) -> None:
    authority, source, views, pins, _ = make_fixture(tmp_path)
    c = load_contract(authority, pins.contract_sha256)
    (source / (c.source_sha256 + ".json")).write_text("{}")
    with pytest.raises(ValueError, match="SHA-256"):
        export_view(source, authority, views, pins)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"warmup_sessions": 0}, "warm-up"),
        ({"train_label_end": "2000-02-09"}, "label crosses"),
        ({"valid_label_end": "2000-03-11"}, "label crosses"),
        ({"embargo_sessions": 3}, "embargo"),
        ({"data_kind": "REAL_MARKET"}, "literal_error"),
        ({"universe": "csi500"}, "literal_error"),
    ],
)
def test_dependency_and_sealed_boundaries(
    tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    authority, _, _, pins, _ = make_fixture(tmp_path)
    c = json.loads(read_blob(authority, pins.contract_sha256))
    DevContract.model_validate_json(canonical(c))
    c.update(change)
    with pytest.raises(ValueError, match=reason):
        DevContract.model_validate_json(canonical(c))


def test_symlinks_hardlinks_and_traversal_are_rejected(tmp_path: Path) -> None:
    store = tmp_path / "store"
    body = b"{}"
    identity = write_blob(store, body)
    alias = tmp_path / "alias"
    alias.symlink_to(store, target_is_directory=True)
    with pytest.raises(OSError):
        read_blob(alias, identity)
    (store / (identity + ".json")).unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(body)
    (store / (identity + ".json")).symlink_to(outside)
    with pytest.raises(OSError):
        read_blob(store, identity)
    (store / (identity + ".json")).unlink()
    os.link(outside, store / (identity + ".json"))
    with pytest.raises(ValueError):
        read_blob(store, identity)
    with pytest.raises(ValueError):
        read_blob(store, "../outside")
    with pytest.raises(ValueError):
        read_blob(store / ".." / "store", identity)
    with pytest.raises(ValueError):
        read_blob(Path("/srv/quant-v2/sealed_holdout"), identity)


def test_interrupted_publication_has_no_complete_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(*args: object, **kwargs: object) -> None:
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr("quant_stack_v2.dev_contract._publish_no_replace", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        write_blob(tmp_path, b"new result")
    assert list(tmp_path.iterdir()) == []


def test_view_content_scope_cannot_be_forged(tmp_path: Path) -> None:
    authority, _, views, pins, vsha = make_fixture(tmp_path)
    manifest = json.loads(read_blob(views, vsha))
    data = json.loads(read_blob(views, manifest["data_sha256"]))
    data["rows"][0]["symbol"] = "SYNTH_OUT"
    manifest["data_sha256"] = write_blob(views, canonical(data))
    forged = write_blob(views, canonical(manifest))
    with pytest.raises(ValueError, match="operator-approved"):
        load_view(authority, views, pins, forged)
    invalid_grant = UsePins(pins.contract_sha256, pins.evidence_sha256, forged)
    with pytest.raises(ValueError, match="scope"):
        load_view(authority, views, invalid_grant, forged)


def test_rehashed_values_still_require_operator_view_pin(tmp_path: Path) -> None:
    authority, _, views, pins, vsha = make_fixture(tmp_path)
    manifest = json.loads(read_blob(views, vsha))
    data = json.loads(read_blob(views, manifest["data_sha256"]))
    data["rows"][0]["values"]["close"] = -999999
    manifest["data_sha256"] = write_blob(views, canonical(data))
    forged = write_blob(views, canonical(manifest))
    with pytest.raises(ValueError, match="operator-approved"):
        load_view(authority, views, pins, forged)
    with pytest.raises(ValueError, match="operator-approved"):
        load_view(authority, views, UsePins(pins.contract_sha256, pins.evidence_sha256), vsha)


def test_boolean_is_not_learning_rate() -> None:
    with pytest.raises(ValueError, match="learning rate"):
        ModelSpec(
            kind="lightgbm",
            seed=1701,
            params={
                "n_estimators": 20,
                "num_leaves": 7,
                "learning_rate": True,
                "min_child_samples": 5,
                "max_depth": 3,
            },
        )


def test_post_publish_interruption_leaves_complete_single_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_stack_v2.dev_contract as module

    publish = module._publish_no_replace

    def interrupted(fd: int, temporary: str, target: str) -> None:
        publish(fd, temporary, target)
        raise OSError("interrupt after atomic rename")

    body = canonical({"result": "synthetic"})
    identity = digest({"result": "synthetic"})
    with monkeypatch.context() as patch:
        patch.setattr(module, "_publish_no_replace", interrupted)
        with pytest.raises(OSError, match="interrupt"):
            write_blob(tmp_path, body)
    assert read_blob(tmp_path, identity) == body
    assert (tmp_path / (identity + ".json")).stat().st_nlink == 1
    assert write_blob(tmp_path, body) == identity


def test_membership_at_T_controls_only_formal_dependencies(tmp_path: Path) -> None:
    from quant_stack_v2.dev_view import dependency_keys

    authority, _, _, pins, _ = make_fixture(tmp_path)
    c = load_contract(authority, pins.contract_sha256)
    day = c.valid.start
    members = (Member(symbol="SYNTH_A", start=day, end=day),)
    keys = dependency_keys(c, members)
    i = c.sessions.index(day)
    assert keys == {("SYNTH_A", c.sessions[j]) for j in [i - 1, i, i + 1, i + 2]}
    assert not any(s == "SYNTH_B" for s, _ in keys)


def test_provider_is_metadata_not_a_qualification_gate(tmp_path: Path) -> None:
    authority, _, _, pins, _ = make_fixture(tmp_path)
    _, evidence = load_evidence(authority, pins)
    assert evidence.kind == "independent_source_scope_verification"
    assert "tushare" not in canonical(evidence).decode().lower()
    assert digest(evidence) == pins.evidence_sha256
    assert DevEvidence.model_validate_json(canonical(evidence)) == evidence


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [("zero_price", "positive"), ("overlap", "overlapping"), ("csi500", "literal_error")],
)
def test_actual_source_semantics_are_verified_before_evidence(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    authority, source, _, pins, _ = make_fixture(tmp_path)
    contract = json.loads(read_blob(authority, pins.contract_sha256))
    payload = json.loads(read_blob(source, contract["source_sha256"]))
    if mutation == "zero_price":
        payload["rows"][0]["values"]["close"] = 0
    elif mutation == "overlap":
        payload["members"].append(payload["members"][0])
    else:
        payload["universe"] = "csi500"
    identity = write_blob(source, canonical(payload))
    contract.update(
        source_sha256=identity, snapshot_sha256=identity, tree_sha256=tree_identity(identity)
    )
    csha = write_blob(authority, canonical(contract))
    with pytest.raises(ValueError, match=reason):
        attest_synthetic(source, authority, csha)


def test_partial_members_export_only_T_eligible_dependencies(tmp_path: Path) -> None:
    from quant_stack_v2.dev_view import dependency_keys

    authority, source, views, pins, _ = make_fixture(tmp_path)
    contract = json.loads(read_blob(authority, pins.contract_sha256))
    payload = json.loads(read_blob(source, contract["source_sha256"]))
    day = contract["valid"]["start"]
    for member in payload["members"]:
        if member["symbol"] == "SYNTH_A":
            member.update(start=day, end=day)
    identity = write_blob(source, canonical(payload))
    contract.update(
        source_sha256=identity, snapshot_sha256=identity, tree_sha256=tree_identity(identity)
    )
    csha = write_blob(authority, canonical(contract))
    esha = attest_synthetic(source, authority, csha)
    vsha = export_view(source, authority, views, UsePins(csha, esha))
    view = load_view(authority, views, UsePins(csha, esha, vsha), vsha)
    assert {(r.symbol, r.session) for r in view.data.rows} == dependency_keys(
        view.contract, view.data.members
    )
    assert len([r for r in view.data.rows if r.symbol == "SYNTH_A"]) == 4


def test_oversized_write_does_not_publish(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bounded size"):
        write_blob(tmp_path, b"x" * (64 * 1024 * 1024 + 1))
    assert list(tmp_path.iterdir()) == []
