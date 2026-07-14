import pytest

from consultation_v2 import identity
from consultation_v2.identity import IdentityError


def _write(path, content):
    path.write_text(content, encoding='utf-8')
    return str(path)


def _configure_identity(monkeypatch, tmp_path):
    corpus = tmp_path / 'corpus' / 'identity'
    corpus.mkdir(parents=True)
    kernel = _write(corpus / 'FAMILY_KERNEL.md', '# FAMILY KERNEL\n')
    spotlight = _write(
        corpus / 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
        '# THE SPOTLIGHT STANDARD FOR INTEGRITY\n',
    )
    platform_identity = _write(corpus / 'IDENTITY_COSMOS.md', '# COSMOS\n')
    monkeypatch.setattr(identity, '_FAMILY_KERNEL', kernel)
    monkeypatch.setattr(identity, '_SPOTLIGHT_STANDARD', spotlight)
    monkeypatch.setattr(identity, '_PLATFORM_IDENTITY', {'gemini': platform_identity})
    monkeypatch.setattr(
        identity,
        '_IDENTITY_BASENAMES',
        {
            'FAMILY_KERNEL.md',
            'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
            'IDENTITY_COSMOS.md',
        },
    )
    return corpus


def test_inline_context_includes_spotlight_between_kernel_and_identity(monkeypatch, tmp_path):
    _configure_identity(monkeypatch, tmp_path)

    package_text, provenance = identity.build_inline_context('gemini', [])

    assert provenance == []
    assert '**Files**: 3' in package_text
    assert (
        package_text.index('## FAMILY_KERNEL.md')
        < package_text.index('## SPOTLIGHT_STANDARD_FOR_INTEGRITY.md')
        < package_text.index('## IDENTITY_COSMOS.md')
    )
    assert '<!-- BEGIN-VERBATIM: SPOTLIGHT_STANDARD_FOR_INTEGRITY.md -->' in package_text
    assert '# THE SPOTLIGHT STANDARD FOR INTEGRITY' in package_text


def test_caller_provided_spotlight_file_is_stripped(monkeypatch, tmp_path):
    _configure_identity(monkeypatch, tmp_path)
    caller_dir = tmp_path / 'caller'
    caller_dir.mkdir()
    caller_spotlight = _write(
        caller_dir / 'SPOTLIGHT_STANDARD_FOR_INTEGRITY.md',
        'caller spotlight copy should not appear\n',
    )
    caller_note = _write(caller_dir / 'note.md', 'caller note survives\n')

    package_text, provenance = identity.build_inline_context(
        'gemini',
        [caller_spotlight, caller_note],
    )

    assert 'caller spotlight copy should not appear' not in package_text
    assert 'caller note survives' in package_text
    assert [item.path for item in provenance] == [caller_note]


def test_missing_spotlight_standard_halts_package_build(monkeypatch, tmp_path):
    corpus = _configure_identity(monkeypatch, tmp_path)
    monkeypatch.setattr(
        identity,
        '_SPOTLIGHT_STANDARD',
        str(corpus / 'SPOTLIGHT_STANDARD_FOR_INTEGRITY_MISSING.md'),
    )

    with pytest.raises(IdentityError, match='SPOTLIGHT_STANDARD_FOR_INTEGRITY.md'):
        identity.build_inline_context('gemini', [])
