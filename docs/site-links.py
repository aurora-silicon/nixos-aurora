"""Keep repository links usable when the guides are published separately."""
import posixpath
import re
from urllib.parse import quote, urlsplit, urlunsplit


def on_page_markdown(markdown, page, **_kwargs):
    def replace(match):
        url = urlsplit(match[2])
        if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
            return match[0]
        path = posixpath.normpath(posixpath.join(posixpath.dirname(page.file.src_uri), url.path))
        renamed = {'README.md': 'reference.md', 'options.md': 'options-reference.md'}
        if path in renamed:
            target = url._replace(path=posixpath.join(posixpath.dirname(url.path), renamed[path])).geturl()
            return match[1] + target + match[3]
        if not path.startswith('../'):
            return match[0]
        repository_path = posixpath.normpath(posixpath.join('docs', path))
        target = urlunsplit(('https', 'github.com',
                            '/aurora-silicon/nixos-aurora/blob/main/' + quote(repository_path),
                            url.query, url.fragment))
        return match[1] + target + match[3]
    return re.sub(r'(\]\()([^\s)]+)(\))', replace, markdown)
