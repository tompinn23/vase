from tomlkit import table, TOMLDocument, float_, integer, string, boolean


class Config:
    def __init__(self, toml: TOMLDocument, section: str):
        self._toml = toml
        self._section = section

        if section not in self._toml:
            self._toml[section] = table()
        self._tbl = self._toml[section]

    def get(self, key, default=None):
        if key not in self._tbl:
            self.set(key, default)
            return default
        return self._tbl[key]

    def set(self, key, value):
        self._tbl[key] = value

    def delete(self, key):
        if key in self._tbl:
            del self._tbl[key]

    def keys(self):
        return self._tbl.keys()

    def items(self):
        return self._tbl.items()

    def __getitem__(self, key):
        return self._tbl[key]

    def __setitem__(self, key, value):
        self._tbl[key] = value

    def __repr__(self):
        return f"<Config section='{self._section}' keys={list(self._tbl.keys())}>"
