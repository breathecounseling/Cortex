from executor.connectors import repl

def test_assessment_trigger_phrases():
    assert repl._assessment_trigger("How can I improve my billing?")
    assert repl._assessment_trigger("Let's talk about client acquisition")
    assert repl._assessment_trigger("I need help with revenue collection")
    assert repl._assessment_trigger("My goal is to optimize intake")

def test_assessment_trigger_specific_directive():
    assert not repl._assessment_trigger("extend ui_builder : add chat input")