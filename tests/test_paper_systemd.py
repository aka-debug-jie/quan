from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_user_timer_is_persistent_and_post_close() -> None:
    timer = (ROOT / "systemd/user/quant-paper.timer").read_text(encoding="utf-8")
    assert "16:20:00 Asia/Shanghai" in timer
    assert "Persistent=true" in timer


def test_service_uses_failure_handler_and_explicit_network_wrapper() -> None:
    service = (ROOT / "systemd/user/quant-paper.service").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts/run_paper_systemd.sh").read_text(encoding="utf-8")
    assert "OnFailure=quant-paper-failure@%n.service" in service
    assert "--allow-network" in wrapper
    assert 'ALLOW_NETWORK" != "1"' in wrapper


def test_install_and_enable_are_separate_actions() -> None:
    install = (ROOT / "scripts/install_paper_systemd_user.sh").read_text(encoding="utf-8")
    enable = (ROOT / "scripts/enable_paper_systemd_user.sh").read_text(encoding="utf-8")
    assert "--preview" in install
    assert "enable --now" not in install
    assert "enable --now quant-paper.timer" in enable
