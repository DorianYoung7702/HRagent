from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_CONSOLE = ROOT / "apps/console-web/src/components/LogConsole.vue"


def test_log_console_has_floating_smooth_scroll_top_button():
    source = LOG_CONSOLE.read_text(encoding="utf-8")

    assert "function scrollTopSmooth()" in source
    assert "containerRef.value?.scrollTo({ top: 0, behavior: 'smooth' })" in source
    assert 'class="log-scroll-top"' in source
    assert 'aria-label="返回日志顶部"' in source
