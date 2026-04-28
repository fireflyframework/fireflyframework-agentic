import pytest
import yaml

from fireflyframework_agentic.prompts import PromptLoader


def test_register_success():
    template = PromptLoader.from_file("tests/test_prompts/assets/valid/valid.yaml.j2")

    assert template.name == "TestTemplate"
    assert template.version == "1.0.0"
    assert template.description == "A test template"
    assert "You are a helpful assistant" in template.system_template
    assert "{{ query }}" in template.user_template
    assert template.required_variables == ["query"]
    assert template.metadata == {"category": "test"}


def test_from_string():
    template = PromptLoader.from_string(
        "MyTemplate",
        system_template="You are helpful.",
        user_template="Answer: {{ question }}",
        version="2.0.0",
        description="inline template",
    )

    assert template.name == "MyTemplate"
    assert template.version == "2.0.0"
    assert template.description == "inline template"
    assert template.system_template == "You are helpful."
    assert template.user_template == "Answer: {{ question }}"


def test_from_directory():
    templates = PromptLoader.from_directory("tests/test_prompts/assets/valid", glob_pattern="*.yaml.j2")

    names = {t.name for t in templates}
    assert "TestTemplate" in names
    assert "AnotherTemplate" in names


def test_from_file_invalid_yaml():
    with pytest.raises((yaml.YAMLError, Exception)):
        PromptLoader.from_file("tests/test_prompts/assets/invalid.yaml.j2")


# def test_register_fail_nonexistent_directory():
#     """Test that registry handles non-existent directory gracefully."""
#     registry = YamlPromptRegistry("tests/assets/prompts/nonexistent")
#     assert len(registry.registry) == 0


# def test_register_fail_invalid_yaml():
#     """Test that registry handles invalid YAML files gracefully."""
#     registry = YamlPromptRegistry("tests/assets/prompts/invalid")
#     assert len(registry.registry) == 0


# def test_register_fail_missing_required_fields():
#     """Test that registry handles templates with missing required fields."""
#     registry = YamlPromptRegistry("tests/assets/prompts/invalid")
#     assert "InvalidTemplate:1.0.0" not in registry.registry


# def test_get_prompt_existing():
#     registry = YamlPromptRegistry("tests/assets/prompts/valid")
#     template = registry.get_prompt_template("TestTemplate", "1.0.0")
#     assert template.name == "TestTemplate"
#     assert template.version == "1.0.0"


# def test_get_prompt_does_not_exist():
#     """Test that ValueError is raised when prompt does not exist."""
#     registry = YamlPromptRegistry("tests/assets/prompts/valid")

#     with pytest.raises(ValueError, match="Prompt 'NonExistent' version '1.0.0' not found in registry"):
#         registry.get_prompt_template("NonExistent", "1.0.0")
