import unittest
from automation.no80_route import audit
from automation.route_runtime import RouteExecutor


class TemplateMinimumTests(unittest.TestCase):
    def fixture(self,target=24):
        policy={'id':'p','cells':5,'target':target}
        route={'version':2,'kind':'stages','cells':10,'minimumTemplateTarget':24,
               'steps':[{'kind':'leaf','policy':'p','target':target,'template':f'5:{target}:single'}]}
        return route,{'policies':[policy]}

    def test_low_target_rejected_before_any_worker_is_loaded(self):
        for target in (6,8,10,12,16):
            route,catalog=self.fixture(target)
            with self.assertRaises(ValueError):audit(route,catalog)
            with self.assertRaises(ValueError):
                RouteExecutor(route,catalog,lambda p:self.fail('Worker must not load'))

    def test_rescue_target_cannot_bypass_floor(self):
        route,catalog=self.fixture()
        catalog['policies'].append({'id':'rescue','cells':5,'target':12})
        route['bufferRescuePolicies']={'12':['rescue']}
        with self.assertRaises(ValueError):audit(route,catalog)
        with self.assertRaises(ValueError):RouteExecutor(route,catalog)

    def test_declared_target_cannot_hide_small_policy(self):
        route,catalog=self.fixture()
        catalog['policies'][0]['target']=6
        with self.assertRaises(ValueError):audit(route,catalog)
        with self.assertRaises(ValueError):RouteExecutor(route,catalog)

    def test_floor_itself_is_allowed(self):
        route,catalog=self.fixture()
        self.assertEqual(audit(route,catalog)['minimumTemplateTarget'],24)
        RouteExecutor(route,catalog).close()

    def test_previously_saved_no80_route_is_also_rejected(self):
        route,catalog=self.fixture(6)
        route.pop('minimumTemplateTarget')
        route['id']='no80-dynamic-final5120-v1'
        with self.assertRaises(ValueError):RouteExecutor(route,catalog)

    def test_warm_input_requires_the_explicit_release_contract(self):
        route,catalog=self.fixture(36)
        step=route['steps'][0]
        prefix=[[5120,1,False]]
        step.update(before=prefix,warmStartOrdinary=18)
        catalog['policies'][0]['warmStartOrdinary']=18
        with self.assertRaises(ValueError):audit(route,catalog)
        release={'kind':'release','before':prefix+[[18,1,False]],'after':prefix,
                 'warmStartOrdinary':18,'releaseIndices':[1]}
        route['steps'].insert(0,release)
        self.assertEqual(audit(route,catalog)['forbiddenPolicies'],[])
        release['before']=prefix+[[16,1,False]]
        with self.assertRaises(ValueError):audit(route,catalog)


if __name__=='__main__':unittest.main()
