"""Stable scope identities and exact allocation-only DetMCD optimizations."""
import unittest
from unittest.mock import patch
import numpy as np
from color_tools.perceptual_grade_core.model import statistics as stats


def original_qn(x):
    x=np.asarray(x,float);n=len(x)
    if n<2:return 0.
    i,j=np.triu_indices(n,1);d=np.abs(x[i]-x[j]);h=n//2+1;k=h*(h-1)//2-1
    return stats.QN_NORMAL*float(np.partition(d,k)[k])


def original_ranks(x):
    order=np.argsort(x,kind='stable');v=x[order];result=np.empty(len(x),float)
    starts=np.r_[0,np.flatnonzero(np.diff(v))+1];ends=np.r_[starts[1:],len(v)]
    for left,right in zip(starts,ends):result[order[left:right]]=(left+right+1)/2
    return result


def original_starts(z):
    n=len(z);h=(n+1)//2
    yield stats.correlation(np.tanh(z))
    r=np.column_stack([original_ranks(z[:,i]) for i in range(2)])
    yield stats.correlation(r)
    normal=np.array([[stats.NORMAL.inv_cdf((v-1/3)/(n+1/3)) for v in row] for row in r])
    yield stats.correlation(normal)
    lengths=np.linalg.norm(z,axis=1)
    signs=np.divide(z,lengths[:,None],out=np.zeros_like(z),where=lengths[:,None]>0)
    yield stats.regular(signs.T@signs/n)
    yield stats.regular(stats.scatter(z[np.argsort(lengths,kind='stable')[:h]])[1])
    v=(original_qn(z[:,0]+z[:,1])**2-original_qn(z[:,0]-z[:,1])**2)/4
    ogk=np.array([[original_qn(z[:,0])**2,v],[v,original_qn(z[:,1])**2]])
    _,e=np.linalg.eigh(ogk)
    yield stats.regular((e*np.array([original_qn((z@e)[:,i])**2 for i in range(2)]))@e.T)


class ScopeSampleTests(unittest.TestCase):
    def test_hash_is_fixed_integer_permutation(self):
        ids=np.array([0,1,2,3,511,512,262143],np.uint64)
        np.testing.assert_array_equal(stats._pixel_hash(ids),np.array([
            16294208416658607535,10451216379200822465,10905525725756348110,
            2092789425003139053,13405271897148188382,18058702125499827302,
            5497625093491408813],np.uint64))

    def test_512_squared_image_has_scattered_distinct_samples(self):
        ids=np.arange(512*512);points=np.column_stack([ids%512,ids//512])
        sample,chosen=stats.hashed_sample(points,np.ones(len(ids)))
        self.assertEqual(len(chosen),512);self.assertEqual(len(np.unique(chosen)),512)
        self.assertGreater(len(np.unique(sample[:,0])),300)
        self.assertGreater(len(np.unique(sample[:,1])),300)
        cells=(sample[:,1].astype(int)//128)*4+sample[:,0].astype(int)//128
        counts=np.bincount(cells,minlength=16)
        self.assertGreater(int(counts.min()),15);self.assertLess(int(counts.max()),55)
        hashes=stats._pixel_hash(ids)
        expected=np.sort(np.argpartition(hashes,len(ids)-512)[-512:])
        np.testing.assert_array_equal(chosen,expected)
        np.testing.assert_array_equal(stats.hashed_sample(points,np.ones(len(ids)))[1],chosen)

    def test_original_ids_preserve_compaction_and_input_permutation(self):
        ids=np.arange(6000);points=np.column_stack([ids,ids*.5])
        weights=np.where((ids%3)==0,.2,np.where((ids%5)==0,1.,0.))
        expected,full=stats.hashed_sample(points,weights)
        keep=np.flatnonzero(weights>0)
        compact,selected=stats.hashed_sample(points[keep],weights[keep],keys=ids[keep])
        np.testing.assert_array_equal(compact,expected)
        np.testing.assert_array_equal(keep[selected],full)
        shuffled=np.random.default_rng(12).permutation(keep)
        _,selected=stats.hashed_sample(points[shuffled],weights[shuffled],keys=ids[shuffled])
        np.testing.assert_array_equal(shuffled[selected],full)

    def test_alpha_bias_has_no_repeated_pixels_and_is_scale_invariant(self):
        ids=np.arange(50000);points=np.column_stack([ids,ids])
        weights=np.where(ids%2,1.,.1)
        _,chosen=stats.hashed_sample(points,weights)
        self.assertGreater(np.count_nonzero(chosen%2),430)
        self.assertEqual(len(np.unique(chosen)),512)
        np.testing.assert_array_equal(stats.hashed_sample(points,weights*.125)[1],chosen)

    def test_small_population_includes_every_finite_positive_alpha_once(self):
        points=np.array([[2.,3.],[5.,6.],[np.nan,1.],[3.,4.],[8.,9.],[7.,8.]])
        weights=np.array([1.,.0001,1.,0.,np.inf,.8])
        sample,chosen=stats.hashed_sample(points,weights,keys=np.array([20,10,40,50,30,15]))
        np.testing.assert_array_equal(chosen,[1,5,0]);np.testing.assert_array_equal(sample,points[chosen])
        for limit in (0,):
            self.assertEqual(stats.hashed_sample(points,weights,limit)[0].shape,(0,2))
        self.assertEqual(stats.hashed_sample(np.empty((0,2)),[])[1].shape,(0,))
        self.assertEqual(stats.hashed_sample(points,np.zeros(len(points)))[1].shape,(0,))

    def test_priority_ties_use_original_id_and_extreme_alpha_stays_finite(self):
        points=np.zeros((5,2));keys=np.array([500,300,400,100,200])
        with patch.object(stats,'_pixel_hash',return_value=np.ones(5,np.uint64)):
            _,chosen=stats.hashed_sample(points,np.ones(5),limit=2,keys=keys)
        np.testing.assert_array_equal(keys[chosen],[100,200])
        weights=np.array([np.nextafter(0.,1.),1e-200,1.,1e200,np.finfo(float).max])
        with np.errstate(all='raise'):
            _,chosen=stats.hashed_sample(points,weights,limit=2)
        np.testing.assert_array_equal(chosen,[3,4])

    def test_invalid_sample_contracts_are_rejected(self):
        points=np.zeros((3,2));weights=np.ones(3)
        for kwargs in (dict(limit=-1),dict(limit=2.5),dict(limit=True),dict(keys=[1,1,2]),
                       dict(keys=[-1,0,1]),dict(keys=[1.,2.,3.]),dict(keys=[1,2]),
                       dict(keys=[[1,2,3]])):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                stats.hashed_sample(points,weights,**kwargs)
        with self.assertRaises(ValueError):stats.hashed_sample(points,weights[:2])

    def test_white_drag_systematic_resampling_is_unchanged(self):
        points=np.column_stack([np.arange(12),np.arange(12)])
        np.testing.assert_array_equal(stats.weighted_sample(points,np.ones(12),4)[1],[1,4,7,10])
        np.testing.assert_array_equal(stats.weighted_sample(points[:3],[.01,.98,.01],3)[1],[1,1,1])


class ExactDetMCDTests(unittest.TestCase):
    def test_qn_matches_allocating_oracle_including_ties_and_degeneracy(self):
        rng=np.random.default_rng(82)
        for n in (0,1,2,3,6,31,128,512):
            for x in (rng.normal(size=n),rng.integers(-4,5,size=n),np.zeros(n)):
                with self.subTest(n=n):self.assertEqual(stats.qn(x),original_qn(x))

    def test_vectorized_ranks_match_original_ties(self):
        rng=np.random.default_rng(83)
        for n in (0,1,6,128,512):
            for x in (rng.normal(size=n),rng.integers(-4,5,size=n),np.zeros(n)):
                np.testing.assert_array_equal(stats.ranks(x),original_ranks(x))

    def test_all_six_starts_match_uncached_oracle(self):
        rng=np.random.default_rng(84)
        for z in (rng.normal(size=(512,2)),rng.integers(-5,6,size=(128,2)).astype(float)):
            for actual,expected in zip(stats.starts(z),original_starts(z)):
                np.testing.assert_array_equal(actual,expected)

    def test_full_fit_matches_original_math_on_identical_samples(self):
        rng=np.random.default_rng(85);outliers=rng.normal(size=(512,2));outliers[-52:]+=8
        populations=(outliers,rng.integers(-5,6,size=(128,2)).astype(float),
                     np.zeros((30,2)),np.array([[0.,0.],[1.,1.],[2.,2.]]))
        for points in populations:
            actual=stats.detmcd(points)
            with patch.object(stats,'qn',original_qn),patch.object(stats,'ranks',original_ranks),\
                 patch.object(stats,'starts',original_starts):expected=stats.detmcd(points)
            for value,reference in zip(actual,expected):np.testing.assert_array_equal(value,reference)

    def test_all_cache_tables_are_readonly_reused_and_bounded(self):
        for function in (stats._qn_indices,stats._normal_scores):
            function.cache_clear();first=function(512)
            self.assertIs(function(512),first);self.assertEqual(function.cache_info().hits,1)
            arrays=first if isinstance(first,tuple) else (first,)
            for values in arrays:
                self.assertFalse(values.flags.writeable)
                with self.assertRaises(ValueError):values[0]=0
            for n in range(6,16):function(n)
            self.assertEqual(function.cache_info().currsize,8)

    def test_description_contains_only_robust_location_and_scatter(self):
        rng=np.random.default_rng(86);points=rng.normal(scale=.01,size=(512,2));points[-40:]+=1
        result=stats.describe_sample(points,min_std=0.)
        self.assertNotIn('mean',result)
        self.assertGreater(np.linalg.norm(np.mean(points,axis=0)-result['center']),.05)
        np.testing.assert_array_equal(result['center'],stats.detmcd(points)[0])
        self.assertEqual(result['count'],512);self.assertFalse(result['reference'])


if __name__=='__main__':unittest.main()
