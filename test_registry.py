import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from weave_registry import fetch_catalog

class LocalCatalogTests(unittest.TestCase):
    def test_relative_runtime_hash_and_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = root / 'runtime.py'
            runtime.write_bytes(b'pass\n')
            digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
            catalog = root / 'catalog.json'
            catalog.write_text(json.dumps({'version':'weave.capabilities.v1','operations':{'calculate':{'runtime_path':'runtime.py','qualified_runtime_sha256':digest,'adapter_ready':True,'programs':{}}}}))
            self.assertTrue(fetch_catalog(path=catalog)['operations']['calculate']['available'])
            runtime.write_bytes(b'changed\n')
            self.assertFalse(fetch_catalog(path=catalog)['operations']['calculate']['available'])

    def test_default_catalog_has_no_available_engines(self):
        catalog = fetch_catalog()
        self.assertTrue(catalog['operations'])
        self.assertTrue(all(not op['available'] for op in catalog['operations'].values()))

    def test_invalid_catalog_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'catalog.json'
            for value in [[], {}, {'version':'weave.capabilities.v1','operations':{'read':[]}}]:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    fetch_catalog(path=path)

    def test_program_hash_is_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'program.json').write_bytes(b'{}')
            path = root/'catalog.json'
            path.write_text(json.dumps({'version':'weave.capabilities.v1','operations':{'read':{'programs':{'p':{'path':'program.json','sha256':'0'*64}}}}}))
            self.assertFalse(fetch_catalog(path=path)['operations']['read']['programs']['p']['available'])

if __name__ == '__main__':
    unittest.main()
