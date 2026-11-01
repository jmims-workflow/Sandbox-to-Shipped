import shutil

import pytest

from sts.demo_data import DemoDataError, check_demo_data, load_demo_data

from .conftest import DEMO_DIR


def copy_demo(tmp_path):
    target = tmp_path / "demo"
    shutil.copytree(DEMO_DIR, target)
    return target


def test_demo_data_is_valid():
    assert check_demo_data(DEMO_DIR) == []
    data = load_demo_data(DEMO_DIR)
    assert len(data.tools) == 9 and len(data.requests) == 8
    assert {d.outcome for d in data.decisions} == {"approve", "approve_with_limits", "use_existing", "not_approved"}


def test_bad_tool_status_names_file_and_field(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "tools.yaml"
    p.write_text(p.read_text().replace("status: retired", "status: gone", 1))
    problems = check_demo_data(demo)
    assert any(x.startswith("demo/tools.yaml, tools[8].status") for x in problems), problems


def test_missing_limits_is_explained(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "tools.yaml"
    p.write_text(p.read_text().replace("    limits: Prices come from the price sheet, never typed in by hand.\n", "", 1))
    problems = check_demo_data(demo)
    assert any("demo/tools.yaml, tools[1]" in x and "limits is required" in x for x in problems), problems


def test_bad_recorded_match_names_file(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "recorded" / "r-1048.json"
    p.write_text(p.read_text().replace('"confidence": "close"', '"confidence": "certain"'))
    problems = check_demo_data(demo)
    assert any(x.startswith("demo/recorded/r-1048.json, matches[0].confidence") for x in problems), problems


def test_unknown_tool_in_recorded_file(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "recorded" / "r-1048.json"
    p.write_text(p.read_text().replace('"tool_id": "call-recap-writer"', '"tool_id": "ghost-tool"'))
    with pytest.raises(DemoDataError) as exc:
        load_demo_data(demo)
    assert "ghost-tool" in str(exc.value)


def test_broken_yaml_is_reported(tmp_path):
    demo = copy_demo(tmp_path)
    (demo / "requests.yaml").write_text("requests: [unclosed")
    assert any("demo/requests.yaml" in x and "not valid YAML" in x for x in check_demo_data(demo))
