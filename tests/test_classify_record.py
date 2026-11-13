import json
import re

import pytest

from opencommune.classify import record


def write_drafts(folder, settings=None):
    settings = settings or json.loads(
        (record.PROMPTS / record.DEFAULT_VERSION / "settings.json").read_text()
    )
    (folder / "p.txt").write_text("Label the document.")
    (folder / "s.json").write_text('{"type": "object"}')
    (folder / "r.json").write_text(json.dumps(settings))
    return folder / "p.txt", folder / "s.json", folder / "r.json"


def test_both_records_of_the_first_implementation_load_unchanged():
    assert {"classify-ac1c5a0746d5", "classify-65e415a748e2"} <= set(record.versions())
    loaded = record.load(record.DEFAULT_VERSION)
    assert loaded.settings.dpi == 75 and loaded.settings.store is False
    assert record.load("classify-ac1c5a0746d5").settings.dpi == 150


def test_a_changed_byte_is_refused(tmp_path):
    version = record.register(*write_drafts(tmp_path), root=tmp_path / "prompts")
    record.load(version, root=tmp_path / "prompts")
    (tmp_path / "prompts" / version / "prompt.txt").write_text("Label the document!")
    with pytest.raises(ValueError, match="do not match"):
        record.load(version, root=tmp_path / "prompts")


def test_a_new_prompt_gets_its_own_version_beside_the_old_ones(tmp_path):
    root = tmp_path / "prompts"
    first = record.register(*write_drafts(tmp_path), root=root)
    (tmp_path / "p.txt").write_text("Label the document, briefly.")
    second = record.register(
        tmp_path / "p.txt", tmp_path / "s.json", tmp_path / "r.json", root=root
    )
    assert first != second and record.versions(root) == sorted([first, second])
    assert record.register(*write_drafts(tmp_path), root=root) == first


@pytest.mark.parametrize("change", [{"store": True}, {"temperature": 0}])
def test_settings_that_keep_data_at_openai_or_are_unknown_are_refused(tmp_path, change):
    settings = json.loads((record.PROMPTS / record.DEFAULT_VERSION / "settings.json").read_text())
    with pytest.raises(ValueError):
        record.register(*write_drafts(tmp_path, settings | change), root=tmp_path / "prompts")


def test_the_default_prompt_lists_what_its_answer_form_allows():
    loaded = record.load(record.DEFAULT_VERSION)
    schema = loaded.schema["properties"]

    def listed(heading):
        part = loaded.prompt.split("## " + heading)[1].split("\n## ")[0]
        return re.findall(r"^- ([a-z_]+):", part, flags=re.M)

    # The prompt orders the document kinds by which one wins, so only the sets are compared.
    assert sorted(listed("Document kinds")) == sorted(schema["document_kind"]["enum"])
    types = schema["sections"]["items"]["properties"]["type"]["enum"]
    assert sorted(listed("Section types")) == sorted(types)
    assert sorted(listed("Body kinds")) == sorted(schema["body_kind"]["enum"])
    fields = loaded.prompt.split("with these fields:")[1].split("Do not guess")[0]
    assert re.findall(r"^- ([a-z_]+):", fields, flags=re.M) == list(schema)
