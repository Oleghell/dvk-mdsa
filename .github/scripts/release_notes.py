"""Extract THIS release's entry from the ever-growing RELEASE_NOTES.md.

GitHub caps release notes at 125000 characters; the full history outgrew the
cap at v1.3.108 (373k characters, 102 release headers), so `gh release create
--notes-file RELEASE_NOTES.md` failed as HTTP 422 'body is too long'. The
release body now carries the CURRENT release's entry only (from its header to
the next one); the complete history stays in the repository file, untouched.
"""
import sys
from pathlib import Path


def entry(version, text):
    head = '# DvkAssistant ' + version + ' '
    start = text.index(head)
    nxt = text.find('\n# DvkAssistant ', start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not args[0]:
        raise SystemExit('usage: release_notes.py VERSION')
    text = Path('RELEASE_NOTES.md').read_text(encoding='utf-8')
    print(entry(args[0], text), end='')


if __name__ == '__main__':
    main()
