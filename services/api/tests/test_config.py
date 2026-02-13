from app.config import Settings


def test_ocr_search_defaults() -> None:
    settings = Settings()
    assert settings.ocr_search_enabled is True
    assert settings.ocr_bm25_boost == 0.6
