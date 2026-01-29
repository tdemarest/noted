"""Integration tests for noted CLI."""

from typer.testing import CliRunner

from noted.cli import app

runner = CliRunner()


def test_help() -> None:
    """Test that help is displayed."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "noted" in result.output.lower()
    assert "list" in result.output
    assert "count" in result.output
    assert "refresh" in result.output


def test_list_help() -> None:
    """Test list command help."""
    result = runner.invoke(app, ["list", "--help"])
    assert result.exit_code == 0
    assert "--folder" in result.output
    assert "--limit" in result.output


def test_count_help() -> None:
    """Test count command help."""
    result = runner.invoke(app, ["count", "--help"])
    assert result.exit_code == 0
    assert "--by-folder" in result.output
