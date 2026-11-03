"""Read bundle count transfers retain source origin and scalar type semantics."""
import unittest
from test_loom import fixture as corpus
from weave_run import validate, unit_for


def fixture():
    return {'version':'weave.pipeline.v1','data_class':'synthetic',
        'plan':{'version':'weave.v1','steps':[
            {'id':'readback','op':'read','inputs':[],'args':{'program_ref':'corpus'}},
            {'id':'counted','op':'calculate','inputs':['readback'],'args':{'program_ref':'count'}}]},
        'programs':{'corpus':corpus(),'count':{'version':'weave.tally.integer.v1','operation':'sum','terms':[0,7],'unit':'count'}},
        'bindings':[{'step':'counted','target':'/terms/0','source_step':'readback','pointer':'/independent_origins','unit':'count'}],
        'checks':[{'kind':'equals','step':'counted','pointer':'/value','value':8}], 'node_options':{}}


class LoomPipelineTests(unittest.TestCase):
    def test_read_bundle_is_a_valid_bounded_root(self):
        self.assertEqual([s['engine'] for s in validate(fixture())],['loom','tally'])

    def test_only_independent_origin_count_is_a_typed_read_scalar(self):
        self.assertEqual(unit_for('read',corpus(),'/independent_origins'),'count')
        for pointer in ['/documents/0/text','/origin_ids/0','/independent_origins/0']:
            with self.subTest(pointer=pointer),self.assertRaises(ValueError):
                unit_for('read',corpus(),pointer)

    def test_text_and_wrong_units_cannot_enter_arithmetic(self):
        for kind in ['text','unit','destination']:
            packet=fixture()
            if kind=='text':packet['bindings'][0]['pointer']='/documents/0/text'
            if kind=='unit':packet['programs']['count']['unit']='integer'
            if kind=='destination':packet['bindings'][0]['target']='/documents/0/text'
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):
                validate(packet)


if __name__=='__main__':unittest.main()
