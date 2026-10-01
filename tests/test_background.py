import pathlib

import streamlit.testing.v1

MAIN_PY_PATH = str(
    pathlib.Path(__file__).parent.parent / "src" / "streamlit_feelcycle" / "main.py"
)


def test_background_logo_applied() -> None:
    at = streamlit.testing.v1.AppTest.from_file(MAIN_PY_PATH)
    at.run(timeout=30)

    # メイン画面のmarkdownに背景ロゴ用のCSSスタイルが含まれていることを検証
    markdown_values = [m.value for m in at.markdown]
    style_markdown = [m for m in markdown_values if "<style>" in m]
    assert len(style_markdown) > 0

    css = style_markdown[0]
    assert 'data-testid="stAppViewContainer"' in css
    assert "data:image/png;base64," in css
    assert "background-repeat: no-repeat;" in css
    assert "background-attachment: fixed;" in css
    assert "background-position: right bottom;" in css
