from research_engine import craft


def test_python_backtest_script_is_not_creative_dialogue_request():
    result = craft.detect(
        "US100/XAUUSD ke liye Python event-driven backtest script banao "
        "aur walk-forward test karo"
    )

    assert result["is_request"] is False
    assert result["reason"] == "technical_script_not_creative"
    assert result["form"] == ""


def test_pine_script_is_not_creative_dialogue_request():
    result = craft.detect(
        "TradingView ke liye Pine Script banao jo US100 entries backtest kare"
    )

    assert result["is_request"] is False
    assert result["reason"] == "technical_script_not_creative"


def test_explicit_dialogue_script_remains_creative():
    result = craft.detect("Do traders ke beech ek dialogue script banao")

    assert result["is_request"] is True
    assert result["form"] == "dialogue"


def test_mixed_technical_topic_with_explicit_dialogue_remains_creative():
    result = craft.detect(
        "Python backtest par do traders ke beech ek dialogue script banao"
    )

    assert result["is_request"] is True
    assert result["form"] == "dialogue"


def test_screenplay_script_remains_creative():
    result = craft.detect("Do characters ke saath ek screenplay script likho")

    assert result["is_request"] is True
    assert result["form"] == "dialogue"


def test_technical_input_characters_are_not_story_characters():
    for question in (
        "Write a Python script to count characters in a string.",
        "Write a Python script to escape special characters.",
        "Write a JavaScript script to analyse conversation logs.",
    ):
        result = craft.detect(question)
        assert result["is_request"] is False, (question, result)


def test_real_creative_request_survives_technical_data_mentions():
    result = craft.detect(
        "Write a screenplay script about two characters who count Unicode characters "
        "using Python and analyse conversation logs."
    )
    assert result["is_request"] is True
    assert result["form"] == "dialogue"
