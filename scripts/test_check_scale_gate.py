"""scripts/check_scale_gate.py 单元测试。对应 designs/precision_tiers_landing-design.md Layer 2。"""

import subprocess
from pathlib import Path

from scripts.check_scale_gate import main


def _init_repo(path: Path, files: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    for rel, content in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)


def test_below_threshold_advisory_exit_0(tmp_path, capsys):
    _init_repo(tmp_path, {"a.py": "x = 1\n", "b.md": "# doc\n"})
    assert main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "源码文件 1 个" in out and "未触发" in out  # b.md 非源码不计


def test_untracked_files_not_counted(tmp_path, capsys):
    _init_repo(tmp_path, {"a.py": "x = 1\n"})
    (tmp_path / "untracked.py").write_text("y = 2\n")
    assert main(["--root", str(tmp_path)]) == 0
    assert "源码文件 1 个" in capsys.readouterr().out


def test_exceed_threshold_strict_exit_1(tmp_path, monkeypatch, capsys):
    import scripts.check_scale_gate as mod

    _init_repo(tmp_path, {"a.py": "x = 1\n"})
    monkeypatch.setattr(mod, "LOC_THRESHOLD", 0)
    assert main(["--root", str(tmp_path)]) == 0  # advisory
    assert main(["--root", str(tmp_path), "--strict"]) == 1
    assert "SCIP" in capsys.readouterr().out


def test_non_git_dir_exit_3(tmp_path, capsys):
    assert main(["--root", str(tmp_path)]) == 3
    assert "无法统计" in capsys.readouterr().err
