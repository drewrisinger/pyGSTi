""" Defines classes which represent gates, as well as supporting functions """
from __future__ import division, print_function, absolute_import, unicode_literals
#*****************************************************************
#    pyGSTi 0.9:  Copyright 2015 Sandia Corporation
#    This Software is released under the GPL license detailed
#    in the file "license.txt" in the top-level pyGSTi directory
#*****************************************************************

import collections as _collections
import itertools as _itertools
import numpy as _np
import scipy as _scipy
import scipy.sparse as _sps

from .. import objects as _objs
from ..tools import basistools as _bt
from ..tools import gatetools as _gt
from ..tools import slicetools as _slct
from ..tools import listtools as _lt
from ..objects.labeldicts import StateSpaceLabels as _StateSpaceLabels

from ..baseobjs import VerbosityPrinter as _VerbosityPrinter
from ..baseobjs.basisconstructors import sqrt2, id2x2, sigmax, sigmay, sigmaz
from ..baseobjs import Basis as _Basis
from ..baseobjs import Label as _Lbl

from . import gatestringconstruction as _gsc
from .gatesetconstruction import basis_build_vector as _basis_build_vector
    

def _iter_basis_inds(weight):
    """ Iterate over product of `weight` non-identity Pauli 1Q basis indices """
    basisIndList = [ [1,2,3] ]*weight #assume pauli 1Q basis, and only iterate over non-identity els
    for basisInds in _itertools.product(*basisIndList):
        yield basisInds

def basisProductMatrix(sigmaInds, sparse):
    """ Construct the Pauli product matrix from the given `sigmaInds` """
    sigmaVec = (id2x2/sqrt2, sigmax/sqrt2, sigmay/sqrt2, sigmaz/sqrt2)
    M = _np.identity(1,'complex')
    for i in sigmaInds:
        M = _np.kron(M,sigmaVec[i])
    return _sps.csr_matrix(M) if sparse else M

def nparams_nqnoise_gateset(nQubits, geometry="line", maxIdleWeight=1, maxhops=0,
                            extraWeight1Hops=0, extraGateWeight=0, requireConnected=False,
                            independent1Qgates=True, ZZonly=False, verbosity=0):
    """
    Returns the number of parameters in the :class:`GateSet` that would be given
    by a call to :function:`build_nqnoise_gateset` with the same parameters, 
    without actually constructing the gate set (useful for considering
    parameter-count scaling).

    Parameters
    ----------
    Same as :function:`build_nqnoise_gateset`
    
    Returns
    -------
    int
    """
    # noise can be either a seed or a random array that is long enough to use

    printer = _VerbosityPrinter.build_printer(verbosity)
    printer.log("Computing parameters for a %d-qubit %s gateset" % (nQubits,geometry))

    qubitGraph = _objs.QubitGraph.common_graph(nQubits, geometry)
    #printer.log("Created qubit graph:\n"+str(qubitGraph))

    def idle_count_nparams(maxWeight):
        """Parameter count of a `build_nqn_global_idle`-constructed gate"""
        ret = 0
        possible_err_qubit_inds = _np.arange(nQubits)
        for wt in range(1,maxWeight+1):
            nErrTargetLocations = qubitGraph.connected_combos(possible_err_qubit_inds,wt)
            if ZZonly and wt > 1: basisSizeWoutId = 1**wt # ( == 1)
            else: basisSizeWoutId = 3**wt # (X,Y,Z)^wt
            nErrParams = 2*basisSizeWoutId # H+S terms
            ret += nErrTargetLocations * nErrParams
        return ret

    def gate_count_nparams(target_qubit_inds,weight_maxhops_tuples,debug=False):
        """Parameter count of a `build_nqn_composed_gate`-constructed gate"""
        ret = 0
        #Note: no contrib from idle noise (already parameterized)
        for wt, maxHops in weight_maxhops_tuples:
            possible_err_qubit_inds = _np.array(qubitGraph.radius(target_qubit_inds, maxHops),'i')
            if requireConnected:
                nErrTargetLocations = qubitGraph.connected_combos(possible_err_qubit_inds,wt)
            else:
                nErrTargetLocations = _scipy.misc.comb(len(possible_err_qubit_inds),wt) #matches actual initial stud
            if ZZonly and wt > 1: basisSizeWoutId = 1**wt # ( == 1)
            else: basisSizeWoutId = 3**wt # (X,Y,Z)^wt
            nErrParams = 2*basisSizeWoutId # H+S terms
            if debug:
                print(" -- wt%d, hops%d: inds=%s locs = %d, eparams=%d, total contrib = %d" %
                      (wt,maxHops,str(possible_err_qubit_inds),nErrTargetLocations,nErrParams,nErrTargetLocations*nErrParams))
            ret += nErrTargetLocations * nErrParams
        return ret

    nParams = _collections.OrderedDict()

    printer.log("Creating Idle:")                
    nParams[_Lbl('Gi')] = idle_count_nparams(maxIdleWeight)
     
    #1Q gates: X(pi/2) & Y(pi/2) on each qubit
    weight_maxhops_tuples_1Q = [(1,maxhops+extraWeight1Hops)] + \
                               [ (1+x,maxhops) for x in range(1,extraGateWeight+1) ]

    if independent1Qgates:
        for i in range(nQubits):
            printer.log("Creating 1Q X(pi/2) and Y(pi/2) gates on qubit %d!!" % i)
            nParams[_Lbl("Gx",i)] = gate_count_nparams((i,), weight_maxhops_tuples_1Q)
            nParams[_Lbl("Gy",i)] = gate_count_nparams((i,), weight_maxhops_tuples_1Q)
    else:
        printer.log("Creating common 1Q X(pi/2) and Y(pi/2) gates")
        rep = int(nQubits / 2)
        nParams[_Lbl("Gxrep")] = gate_count_nparams((rep,), weight_maxhops_tuples_1Q)
        nParams[_Lbl("Gyrep")] = gate_count_nparams((rep,), weight_maxhops_tuples_1Q)

    #2Q gates: CNOT gates along each graph edge
    weight_maxhops_tuples_2Q = [(1,maxhops+extraWeight1Hops),(2,maxhops)] + \
                               [ (2+x,maxhops) for x in range(1,extraGateWeight+1) ]
    for i,j in qubitGraph.edges(): #note: all edges have i<j so "control" of CNOT is always lower index (arbitrary)
        printer.log("Creating CNOT gate between qubits %d and %d!!" % (i,j))
        nParams[_Lbl("Gcnot",(i,j))] = gate_count_nparams((i,j), weight_maxhops_tuples_2Q)

    #SPAM
    nPOVM_1Q = 4 # params for a single 1Q POVM
    nParams[_Lbl('rho0')] = 3*nQubits # 3 b/c each component is TP
    nParams[_Lbl('Mdefault')] = nPOVM_1Q * nQubits # nQubits 1Q-POVMs

    return nParams, sum(nParams.values())



def build_nqnoise_gateset(nQubits, geometry="line", maxIdleWeight=1, maxhops=0,
                          extraWeight1Hops=0, extraGateWeight=0, sparse=False,
                          gateNoise=None, prepNoise=None, povmNoise=None,
                          sim_type="matrix", parameterization="H+S", verbosity=0): #, debug=False):
    """ 
    Create a noisy n-qubit gateset using a low-weight and geometrically local
    error model with a common idle gate.  

    This type of gateset is generally useful for performing GST on a multi-
    qubit gateset, whereas functions like :function:`build_nqubit_gateset`
    are more useful for creating static (non-parameterized) gate sets.

    Parameters
    ----------
    nQubits : int
        The number of qubits
    
    geometry : {"line","ring","grid","torus"}
        The type of connectivity among the qubits.

    maxIdleWeight : int, optional
        The maximum-weight for errors on the global idle gate.

    maxhops : int
        The locality constraint: for a gate, errors (of weight up to the
        maximum weight for the gate) are allowed to occur on the gate's
        target qubits and those reachable by hopping at most `maxhops` times
        from a target qubit along nearest-neighbor links (defined by the 
        `geometry`).  
    
    extraWeight1Hops : int, optional
        Additional hops (adds to `maxhops`) for weight-1 errors.  A value > 0
        can be useful for allowing just weight-1 errors (of which there are 
        relatively few) to be dispersed farther from a gate's target qubits.
        For example, a crosstalk-detecting model might use this.
    
    extraGateWeight : int, optional
        Addtional weight, beyond the number of target qubits (taken as a "base
        weight" - i.e. weight 2 for a 2Q gate), allowed for gate errors.  If
        this equals 1, for instance, then 1-qubit gates can have up to weight-2
        errors and 2-qubit gates can have up to weight-3 errors.

    sparse : bool, optional
        Whether the embedded Lindblad-parameterized gates within the constructed
        `nQubits`-qubit gates are sparse or not.  (This is determied by whether
        they are constructed using sparse basis matrices.)  When sparse, these
        Lindblad gates take up less memory, but their action is slightly slower.
        Usually it's fine to leave this as the default (False), except when
        considering particularly high-weight terms (b/c then the Lindblad gates
        are higher dimensional and sparsity has a significant impact).

    gateNoise, prepNoise, povmNoise : tuple or numpy.ndarray, optional
        If not None, noise to place on the gates, the state prep and the povm.
        This can either be a `(seed,strength)` 2-tuple, or a long enough numpy
        array (longer than what is needed is OK).  These values specify random
        `gate.from_vector` initializatin for the gates and random depolarization
        amounts on the preparation and POVM.

    sim_type : {"auto","matrix","map","termorder:<N>"}
        The type of forward simulation (probability computation) to use for the
        returned :class:`GateSet`.  That is, how should the gate set compute
        gate string/circuit probabilities when requested.  `"matrix"` is better
        for small numbers of qubits, `"map"` is better for larger numbers. The
        `"termorder"` option is designed for even larger numbers.  Usually,
        the default of `"auto"` is what you want.
    
    parameterization : {"H+S", "H+S terms", "H+S clifford terms"}
        The type of parameterizaton to use in the constructed gate set.  The
        default of `"H+S"` performs usual density-matrix evolution to compute
        circuit probabilities.  The other "terms" options compute probabilities
        using a path-integral approach designed for larger numbers of qubits,
        and are considered expert options.

    verbosity : int, optional
        An integer >= 0 dictating how must output to send to stdout.

    Returns
    -------
    GateSet
    """

    assert(parameterization in ("H+S","H+S terms","H+S clifford terms"))
    if sim_type == "auto":
        if parameterization in ("H+S terms", "H+S clifford terms"): sim_type = "termorder:1"
        else: sim_type = "map" if nQubits > 2 else "matrix"

    assert(sim_type in ("matrix","map") or sim_type.startswith("termorder"))

    from pygsti.construction import std1Q_XY # the base gate set for 1Q gates
    from pygsti.construction import std2Q_XYICNOT # the base gate set for 2Q (CNOT) gate
    
    # noise can be either a seed or a random array that is long enough to use

    printer = _VerbosityPrinter.build_printer(verbosity)
    geometry_name = "custom" if isinstance(geometry, _objs.QubitGraph) else geometry
    printer.log("Creating a %d-qubit %s gateset" % (nQubits,geometry_name))

    gs = _objs.GateSet(sim_type=sim_type, default_param=parameterization) # no preps/POVMs
    gs.stateSpaceLabels = _StateSpaceLabels(list(range(nQubits))) #TODO: better way of setting this... (__init__?)
    
    # OLD: sim_type = "map" if sparse else "matrix") # no preps/POVMs
    
    # TODO: sparse prep & effect vecs... acton(...) analogue?

    #Full preps & povms -- maybe another option
    ##Create initial gate set with std prep & POVM
    #eLbls = []; eExprs = []
    #formatStr = '0' + str(nQubits) + 'b'
    #for i in range(2**nQubits):
    #    eLbls.append( format(i,formatStr))
    #    eExprs.append( str(i) )    
    #Qlbls = tuple( ['Q%d' % i for i in range(nQubits)] )
    #gs = pygsti.construction.build_gateset(
    #    [2**nQubits], [Qlbls], [], [], 
    #    effectLabels=eLbls, effectExpressions=eExprs)
    printer.log("Created initial gateset")

    if isinstance(geometry, _objs.QubitGraph):
        qubitGraph = geometry
    else:
        qubitGraph = _objs.QubitGraph.common_graph(nQubits, geometry)
    printer.log("Created qubit graph:\n"+str(qubitGraph))

    if maxIdleWeight > 0:
        printer.log("Creating Idle:")
        gs.gates[_Lbl('Gi')] = build_nqn_global_idle(qubitGraph, maxIdleWeight, sparse,
                                                     sim_type, parameterization, printer-1)
        idleOP = gs.gates['Gi']
    else:
        gs._dim = 4**nQubits # TODO: make a set_dim that does this (and is used in labeldicts.py)
        if gs._sim_type == "auto":
            gs.set_simtype("auto") # run deferred auto-simtype now that _dim is set

        idleOP = False

    #1Q gates: X(pi/2) & Y(pi/2) on each qubit
    Gx = std1Q_XY.gs_target.gates['Gx']
    Gy = std1Q_XY.gs_target.gates['Gy'] 
    weight_maxhops_tuples_1Q = [(1,maxhops+extraWeight1Hops)] + \
                               [ (1+x,maxhops) for x in range(1,extraGateWeight+1) ]
    for i in range(nQubits):
        printer.log("Creating 1Q X(pi/2) gate on qubit %d!!" % i)
        gs.gates[_Lbl("Gx",i)] = build_nqn_composed_gate(
            Gx, (i,), qubitGraph, weight_maxhops_tuples_1Q,
            idle_noise=idleOP, loc_noise_type="manylittle",
            sparse=sparse, sim_type=sim_type, parameterization=parameterization,
            verbosity=printer-1)

        printer.log("Creating 1Q Y(pi/2) gate on qubit %d!!" % i)
        gs.gates[_Lbl("Gy",i)] = build_nqn_composed_gate(
            Gy, (i,), qubitGraph, weight_maxhops_tuples_1Q,
            idle_noise=idleOP, loc_noise_type="manylittle",
            sparse=sparse, sim_type=sim_type, parameterization=parameterization,
            verbosity=printer-1)
        
    #2Q gates: CNOT gates along each graph edge
    Gcnot = std2Q_XYICNOT.gs_target.gates['Gcnot']
    weight_maxhops_tuples_2Q = [(1,maxhops+extraWeight1Hops),(2,maxhops)] + \
                               [ (2+x,maxhops) for x in range(1,extraGateWeight+1) ]
    for i,j in qubitGraph.edges(): #note: all edges have i<j so "control" of CNOT is always lower index (arbitrary)
        printer.log("Creating CNOT gate between qubits %d and %d!!" % (i,j))
        gs.gates[_Lbl("Gcnot",(i,j))] = build_nqn_composed_gate(
            Gcnot, (i,j), qubitGraph, weight_maxhops_tuples_2Q,
            idle_noise=idleOP, loc_noise_type="manylittle",
            sparse=sparse, sim_type=sim_type, parameterization=parameterization,
            verbosity=printer-1)


    #Insert noise on gates
    vecNoSpam = gs.to_vector()
    assert( _np.linalg.norm(vecNoSpam)/len(vecNoSpam) < 1e-6 )
    if gateNoise is not None:
        if isinstance(gateNoise,tuple): # use as (seed, strength)
            seed,strength = gateNoise
            rndm = _np.random.RandomState(seed)
            vecNoSpam += _np.abs(rndm.random_sample(len(vecNoSpam))*strength) #abs b/c some params need to be positive
        else: #use as a vector
            vecNoSpam += gateNoise[0:len(vecNoSpam)]
        gs.from_vector(vecNoSpam)

        
    #SPAM
    basis1Q = _Basis("pp",2)
    prep_factors = []; povm_factors = []

    v0 = _basis_build_vector("0", basis1Q)
    v1 = _basis_build_vector("1", basis1Q)

    typ = parameterization
    povmtyp = rtyp = "TP" if typ in ("CPTP","H+S","S") else typ  # use TP until we have LindbladParameterizedSPAMVecs

    #DEBUG - make spam static for now (modified convert() in spamvec.py and povm.py for terms - see "DEBUG!!!")
    #if debug:
    #    if rtyp in ("TP",): rtyp = "static"
    #    if povmtyp in ("TP",): povmtyp = "static"

    for i in range(nQubits):
        prep_factors.append(
            _objs.spamvec.convert(_objs.StaticSPAMVec(v0), rtyp, basis1Q) )
        povm_factors.append(
            _objs.povm.convert(_objs.UnconstrainedPOVM( ([
                ('0',_objs.StaticSPAMVec(v0)),
                ('1',_objs.StaticSPAMVec(v1))]) ), povmtyp, basis1Q) )

    if prepNoise is not None:
        if isinstance(prepNoise,tuple): # use as (seed, strength)
            seed,strength = prepNoise
            rndm = _np.random.RandomState(seed)
            depolAmts = _np.abs(rndm.random_sample(nQubits)*strength)
        else:
            depolAmts = prepNoise[0:nQubits]
        for amt,vec in zip(depolAmts,prep_factors): vec.depolarize(amt)

    if povmNoise is not None:
        if isinstance(povmNoise,tuple): # use as (seed, strength)
            seed,strength = povmNoise
            rndm = _np.random.RandomState(seed)
            depolAmts = _np.abs(rndm.random_sample(nQubits)*strength)
        else:
            depolAmts = povmNoise[0:nQubits]
        for amt,povm in zip(depolAmts,povm_factors): povm.depolarize(amt) 
           
    gs.preps[_Lbl('rho0')] = _objs.TensorProdSPAMVec('prep', prep_factors)
    gs.povms[_Lbl('Mdefault')] = _objs.TensorProdPOVM(povm_factors)



    ##OLD - before we had Lindblad SPAMVecs
    #prepFactors = [ pygsti.obj.TPParameterizedSPAMVec(pygsti.construction.basis_build_vector("0", basis1Q))
    #                for i in range(nQubits)]
    #if prepNoise is not None:
    #    if isinstance(prepNoise,tuple): # use as (seed, strength)
    #        seed,strength = prepNoise
    #        rndm = _np.random.RandomState(seed)
    #        depolAmts = _np.abs(rndm.random_sample(nQubits)*strength)
    #    else:
    #        depolAmts = prepNoise[0:nQubits]
    #    for amt,vec in zip(depolAmts,prepFactors): vec.depolarize(amt) 
    #gs.preps['rho0'] = pygsti.obj.TensorProdSPAMVec('prep',prepFactors)
    #
    #factorPOVMs = []
    #for i in range(nQubits):
    #    effects = [ (l,pygsti.construction.basis_build_vector(l, basis1Q)) for l in ["0","1"] ]
    #    factorPOVMs.append( pygsti.obj.TPPOVM(effects) )
    #if povmNoise is not None:
    #    if isinstance(povmNoise,tuple): # use as (seed, strength)
    #        seed,strength = povmNoise
    #        rndm = _np.random.RandomState(seed)
    #        depolAmts = _np.abs(rndm.random_sample(nQubits)*strength)
    #    else:
    #        depolAmts = povmNoise[0:nQubits]
    #    for amt,povm in zip(depolAmts,factorPOVMs): povm.depolarize(amt) 
    #gs.povms['Mdefault'] = pygsti.obj.TensorProdPOVM( factorPOVMs )
        
    printer.log("DONE! - returning GateSet with dim=%d and gates=%s" % (gs.dim, list(gs.gates.keys())))
    return gs
    

def _get_Lindblad_factory(sim_type, parameterization):
    """ Returns a function that creates a Lindblad-type gate appropriate
        given the simulation type and parameterization """
    if parameterization == "H+S":
        evotype = "densitymx"
        cls = _objs.LindbladParameterizedGate if sim_type == "matrix" \
              else _objs.LindbladParameterizedGateMap

    elif parameterization in ("H+S terms","H+S clifford terms"):
        assert(sim_type.startswith("termorder"))
        evotype = "svterm" if parameterization == "H+S terms" else "cterm"
        cls = _objs.LindbladParameterizedGateMap
    else:
        raise ValueError("Cannot create Lindblad gate factory for ",sim_type, parameterization)

    #Just call cls.from_gate_matrix with appropriate evotype
    def _f(gateMatrix, unitaryPostfactor=None,
          ham_basis="pp", nonham_basis="pp", cptp=True,
          nonham_diagonal_only=False, truncate=True, mxBasis="pp"):
        return cls.from_gate_matrix(gateMatrix, unitaryPostfactor,
                                    ham_basis, nonham_basis, cptp,
                                    nonham_diagonal_only, truncate,
                                    mxBasis, evotype)
    return _f
                                    

def _get_Static_factory(sim_type, parameterization):
    """ Returns a function that creates a static-type gate appropriate 
        given the simulation and parameterization """
    if parameterization == "H+S":
        if sim_type == "matrix":
            return lambda g,b: _objs.StaticGate(g)
        elif sim_type == "map":
            return lambda g,b: _objs.StaticGate(g) # TODO: create StaticGateMap

    elif parameterization in ("H+S terms","H+S clifford terms"):
        assert(sim_type.startswith("termorder"))
        evotype = "svterm" if parameterization == "H+S terms" else "cterm"
        
        def _f(gateMatrix, mxBasis="pp"):
            return _objs.LindbladParameterizedGateMap.from_gate_matrix(
                None, gateMatrix, None, None, mxBasis=mxBasis, evotype=evotype)
                # a LindbladParameterizedGate with None as ham_basis and nonham_basis => no parameters
              
        return _f
    raise ValueError("Cannot create Static gate factory for ",sim_type, parameterization)


def build_nqn_global_idle(qubitGraph, maxWeight, sparse=False, sim_type="matrix", parameterization="H+S", verbosity=0):
    """
    Create a "global" idle gate, meaning one that acts on all the qubits in 
    `qubitGraph`.  The gate will have up to `maxWeight` errors on *connected*
    (via the graph) sets of qubits.

    Parameters
    ----------
    qubitGraph : QubitGraph
        A graph giving the geometry (nearest-neighbor relations) of the qubits.

    maxWeight : int
        The maximum weight errors to include in the resulting gate.

    sparse : bool, optional
        Whether the embedded Lindblad-parameterized gates within the constructed
        gate are represented as sparse or dense matrices.  (This is determied by
        whether they are constructed using sparse basis matrices.)

    sim_type : {"matrix","map","termorder:<N>"}
        The type of forward simulation (probability computation) being used by 
        the gate set this gate is destined for.  This affects what type of 
        gate objects (e.g. `ComposedGate` vs `ComposedGateMap`) are created.
    
    parameterization : {"H+S", "H+S terms", "H+S clifford terms"}
        The type of parameterizaton for the constructed gate.

    verbosity : int, optional
        An integer >= 0 dictating how must output to send to stdout.

    Returns
    -------
    Gate
    """
    assert(maxWeight <= 2), "Only `maxWeight` equal to 0, 1, or 2 is supported"

    if sim_type == "matrix": 
        Composed = _objs.ComposedGate
        Embedded = _objs.EmbeddedGate
    else:
        Composed = _objs.ComposedGateMap
        Embedded = _objs.EmbeddedGateMap
    Lindblad = _get_Lindblad_factory(sim_type, parameterization)
    
    printer = _VerbosityPrinter.build_printer(verbosity)
    printer.log("*** Creating global idle ***")
    
    termgates = [] # gates to compose
    ssAllQ = [tuple(['Q%d'%i for i in range(qubitGraph.nqubits)])]
    basisAllQ = _Basis('pp', 2**qubitGraph.nqubits, sparse=sparse) # TODO: remove - all we need is its 'dim' below
    
    nQubits = qubitGraph.nqubits
    possible_err_qubit_inds = _np.arange(nQubits)
    nPossible = nQubits  
    for wt in range(1,maxWeight+1):
        printer.log("Weight %d: %d possible qubits" % (wt,nPossible),2)
        basisEl_Id = basisProductMatrix(_np.zeros(wt,'i'),sparse)
        wtId = _sps.identity(4**wt,'d','csr') if sparse else  _np.identity(4**wt,'d')
        wtBasis = _Basis('pp', 2**wt, sparse=sparse)
        
        for err_qubit_inds in _itertools.combinations(possible_err_qubit_inds, wt):
            if len(err_qubit_inds) == 2 and not qubitGraph.is_directly_connected(err_qubit_inds[0],err_qubit_inds[1]):
                continue # TO UPDATE - check whether all wt indices are a connected subgraph

            errbasis = [basisEl_Id]
            for err_basis_inds in _iter_basis_inds(wt):        
                error = _np.array(err_basis_inds,'i') #length == wt
                basisEl = basisProductMatrix(error,sparse)
                errbasis.append(basisEl)

            printer.log("Error on qubits %s -> error basis of length %d" % (err_qubit_inds,len(errbasis)), 3)
            errbasis = _Basis(matrices=errbasis, sparse=sparse) #single element basis (plus identity)
            termErr = Lindblad(wtId, ham_basis=errbasis, nonham_basis=errbasis, cptp=True,
                               nonham_diagonal_only=True, truncate=True, mxBasis=wtBasis)
        
            err_qubit_global_inds = err_qubit_inds
            fullTermErr = Embedded(ssAllQ, [('Q%d'%i) for i in err_qubit_global_inds],
                                   termErr, basisAllQ.dim)
            assert(fullTermErr.num_params() == termErr.num_params())
            printer.log("Lindblad gate w/dim=%d and %d params -> embedded to gate w/dim=%d" %
                        (termErr.dim, termErr.num_params(), fullTermErr.dim))
                    
            termgates.append( fullTermErr )
                
    return Composed(termgates)         
    
    

#def build_nqn_noncomposed_gate(targetOp, target_qubit_inds, qubitGraph, maxWeight, maxHops,
#                            spectatorMaxWeight=1, mode="embed"):
#
#    assert(spectatorMaxWeight <= 1) #only 0 and 1 are currently supported
#    
#    errinds = [] # list of basis indices for all error terms
#    possible_err_qubit_inds = _np.array(qubitGraph.radius(target_qubit_inds, maxHops),'i')
#    nPossible = len(possible_err_qubit_inds)
#    for wt in range(maxWeight+1):
#        if mode == "no-embedding": # make an error term for the entire gate
#            for err_qubit_inds in _itertools.combinations(possible_err_qubit_inds, wt):
#                # err_qubit_inds are global qubit indices
#                #Future: check that err_qubit_inds marks qubits that are connected
#                
#                for err_basis_inds in iter_basis_inds(wt):  
#                    error = _np.zeros(nQubits)
#                    error[ possible_err_qubit_inds[err_qubit_inds] ] = err_basis_inds
#                    errinds.append( error )
#                    
#        elif mode == "embed": # make an error term for only the "possible error" qubits
#                              # which will get embedded to form a full gate
#            for err_qubit_inds in _itertools.combinations(list(range(nPossible)), wt):
#                # err_qubit_inds are indices into possible_err_qubit_inds
#                #Future: check that err_qubit_inds marks qubits that are connected
#                
#                for err_basis_inds in iter_basis_inds(wt):  
#                    error = _np.zeros(nPossible)
#                    error[ err_qubit_inds ] = err_basis_inds
#                    errinds.append( error )
#
#    errbasis = [ basisProductMatrix(err) for err in errinds]
#    
#    ssAllQ = ['Q%d'%i for i in range(qubitGraph.nqubits)]
#    basisAllQ = pygsti.objects.Basis('pp', 2**qubitGraph.nqubits)
#    
#    if mode == "no-embedding":     
#        fullTargetOp = EmbeddedGate(ssAllQ, ['Q%d'%i for i in target_qubit_inds],
#                                    targetOp, basisAllQ) 
#        fullTargetOp = StaticGate( fullTargetOp ) #Make static
#        fullLocalErr = LindbladParameterizedGate(fullTargetOp, fullTargetOp,
#                         ham_basis=errbasis, nonham_basis=errbasis, cptp=True,
#                         nonham_diagonal_only=True, truncate=True, mxBasis=basisAllQ)
#          # gate on full qubit space that accounts for error on the "local qubits", that is,
#          # those local to the qubits being operated on
#    elif mode == "embed":
#        possible_list = list(possible_err_qubit_inds)
#        loc_target_inds = [possible_list.index(i) for i in target_qubit_inds]
#        
#        ssLocQ = ['Q%d'%i for i in range(nPossible)]
#        basisLocQ = pygsti.objects.Basis('pp', 2**nPossible)
#        locTargetOp = StaticGate( EmbeddedGate(ssLocQ, ['Q%d'%i for i in loc_target_inds],
#                                    targetOp, basisLocQ) )
#        localErr = LindbladParameterizedGate(locTargetOp, locTargetOp,
#                         ham_basis=errbasis, nonham_basis=errbasis, cptp=True,
#                         nonham_diagonal_only=True, truncate=True, mxBasis=basisLocQ)
#        fullLocalErr = EmbeddedGate(ssAllQ, ['Q%d'%i for i in possible_err_qubit_inds],
#                                   localErr, basisAllQ)
#    else:
#        raise ValueError("Invalid Mode: %s" % mode)
#        
#    #Now add errors on "non-local" i.e. spectator gates
#    if spectatorMaxWeight == 0:
#        pass
#    #STILL in progress -- maybe just non-embedding case, since if we embed we'll
#    # need to compose (in general)
        

        
def build_nqn_composed_gate(targetOp, target_qubit_inds, qubitGraph, weight_maxhops_tuples,
                            idle_noise=False, loc_noise_type="onebig",
                            apply_idle_noise_to="all", sparse=False, sim_type="matrix",
                            parameterization="H+S", verbosity=0):
    """ 
    Create an n-qubit gate that is a composition of:
    
    `targetOp(target_qubits) -> idle_noise(all_qubits) -> loc_noise(local_qubits)`

    where `idle_noise` is given by the `idle_noise` argument and `loc_noise` is
    given by the rest of the arguments.  `loc_noise` can be implemented either
    by a single (n-qubit) embedded Lindblad gate with all relevant error
    generators, or as a composition of embedded single-error-term Lindblad gates
    (see param `loc_noise_type`).

    The local noise consists terms up to a maximum weight acting on the qubits
    given reachable by a given maximum number of hops (along the neareset-
    neighbor edges of `qubitGraph`) from the target qubits.


    Parameters
    ----------
    targetOp : numpy array
        The target operation as a dense matrix, specifying the action on just
        the target qubits.

    target_qubit_inds : list
        The indices of the target qubits.
        
    qubitGraph : QubitGraph
        A graph giving the geometry (nearest-neighbor relations) of the qubits.

    weight_maxhops_tuples : iterable
        A list of `(weight,maxhops)` 2-tuples specifying which error weights
        should be included and what region of the graph (as a `maxhops` from
        the set of target qubits) should have errors of the given weight applied
        to it.

    idle_noise : Gate or boolean
        Either given as an existing gate (on all qubits) or a boolean indicating
        whether a composition of weight-1 noise terms (separately on all the qubits),
        is created.  If `apply_idle_noise_to == "nonlocal"` then `idle_noise` is *only*
        applied to the non-local qubits and `idle_noise` must be a ComposedGate or
        ComposedMap with `nQubits` terms so that individual terms for each qubit can
        be extracted as needed.


    loc_noise_type : {"onebig","manylittle"}
        Whether the `loc_noise` portion of the constructed gate should be a
        a single Lindblad gate containing all the allowed error terms (onebig)
        or the composition of many Lindblad gates each containing just a single
        error term (manylittle).  The resulting gate performs the same action
        regardless of the value set here; this just affects how the gate is
        structured internally.

    apply_idle_noise_to : {"all","nonlocal"}
        Whether the `idle_noise` argument represents a Gate to be applied to 
        *all* the qubits or whether it is a composed Gate with `nqubits` terms
        that can be selectively applied only to the non-local qubits. (i.e.
        those that are more than max-hops away from the target qubits).

    sparse : bool, optional
        Whether the embedded Lindblad-parameterized gates within the constructed
        gate are represented as sparse or dense matrices.  (This is determied by
        whether they are constructed using sparse basis matrices.)

    sim_type : {"matrix","map","termorder:<N>"}
        The type of forward simulation (probability computation) being used by 
        the gate set this gate is destined for.  This affects what type of 
        gate objects (e.g. `ComposedGate` vs `ComposedGateMap`) are created.
    
    parameterization : {"H+S", "H+S terms", "H+S clifford terms"}
        The type of parameterizaton for the constructed gate.

    verbosity : int, optional
        An integer >= 0 dictating how must output to send to stdout.

    Returns
    -------
    Gate
    """
    if sim_type == "matrix": 
        Composed = _objs.ComposedGate
        Embedded = _objs.EmbeddedGate
    else:
        Composed = _objs.ComposedGateMap
        Embedded = _objs.EmbeddedGateMap
    Static = _get_Static_factory(sim_type, parameterization)
    Lindblad = _get_Lindblad_factory(sim_type, parameterization)

    ##OLD
    #if sparse:
    #    Lindblad = _objs.LindbladParameterizedGateMap
    #    Composed = _objs.ComposedGateMap
    #    Embedded = _objs.EmbeddedGateMap
    #    Static = _objs.StaticGate # TODO: create StaticGateMap
    #else:
    #    Lindblad = _objs.LindbladParameterizedGate
    #    Composed = _objs.ComposedGate
    #    Embedded = _objs.EmbeddedGate
    #    Static = _objs.StaticGate
    
    printer = _VerbosityPrinter.build_printer(verbosity)
    printer.log("*** Creating composed gate ***")
    
    #Factor1: target operation
    printer.log("Creating %d-qubit target op factor on qubits %s" %
                (len(target_qubit_inds),str(target_qubit_inds)),2)
    ssAllQ = [tuple(['Q%d'%i for i in range(qubitGraph.nqubits)])]
    basisAllQ = _Basis('pp', 2**qubitGraph.nqubits, sparse=sparse)
    fullTargetOp = Embedded(ssAllQ, ['Q%d'%i for i in target_qubit_inds],
                            Static(targetOp,"pp"), basisAllQ.dim) 

    #Factor2: idle_noise operation
    printer.log("Creating idle error factor",2)
    if apply_idle_noise_to == "all":
        if isinstance(idle_noise, _objs.Gate):
            printer.log("Using supplied full idle gate",3)
            fullIdleErr = idle_noise
        elif idle_noise == True:
            #build composition of 1Q idle ops
            printer.log("Constructing independend weight-1 idle gate",3)
            # Id_1Q = _sps.identity(4**1,'d','csr') if sparse else  _np.identity(4**1,'d')
            Id_1Q = _np.identity(4**1,'d') #always dense for now...
            fullIdleErr = Composed(
                [ Embedded(ssAllQ, ('Q%d'%i,), Lindblad(Id_1Q.copy()),basisAllQ.dim)
                  for i in range(qubitGraph.nqubits)] )
        elif idle_noise == False:
            printer.log("No idle factor",3)
            fullIdleErr = None
        else:
            raise ValueError("Invalid `idle_noise` argument")
            
    elif apply_idle_noise_to == "nonlocal":
        pass #TODO: only apply (1Q) idle noise to qubits that don't have 1Q local noise.
        assert(False)
    
    else:
        raise ValueError('Invalid `apply_idle_noise_to` argument: %s' % apply_idle_noise_to)

        
    #Factor3: local_noise operation
    printer.log("Creating local-noise error factor (%s)" % loc_noise_type,2)
    if loc_noise_type == "onebig": 
        # make a single embedded Lindblad-gate containing all specified error terms
        loc_noise_errinds = [] # list of basis indices for all local-error terms
        all_possible_err_qubit_inds = _np.array( qubitGraph.radius(
            target_qubit_inds, max([hops for _,hops in weight_maxhops_tuples]) ), 'i') # node labels are ints
        nLocal = len(all_possible_err_qubit_inds)
        basisEl_Id = basisProductMatrix(_np.zeros(nPossible,'i'),sparse) #identity basis el
        
        for wt, maxHops in weight_maxhops_tuples:
            possible_err_qubit_inds = _np.array(qubitGraph.radius(target_qubit_inds, maxHops),'i') # node labels are ints
            nPossible = len(possible_err_qubit_inds)
            possible_to_local = [ all_possible_err_qubit_inds.index(
                possible_err_qubit_inds[i]) for i in range(nPossible)]
            printer.log("Weight %d, max-hops %d: %d possible qubits of %d local" %
                        (wt,maxHops,nPossible,nLocal),3)
            
            for err_qubit_inds in _itertools.combinations(list(range(nPossible)), wt):
                # err_qubit_inds are in range [0,nPossible-1] qubit indices
                #Future: check that err_qubit_inds marks qubits that are connected
                err_qubit_local_inds = possible_to_local[err_qubit_inds]
                                                        
                for err_basis_inds in _iter_basis_inds(wt):  
                    error = _np.zeros(nLocal,'i')
                    error[ err_qubit_local_inds ] = err_basis_inds
                    loc_noise_errinds.append( error )
                    
                printer.log("Error on qubits %s -> error basis now at length %d" %
                            (all_possible_err_qubit_inds[err_qubit_local_inds],1+len(loc_noise_errinds)), 4)
                
        errbasis = [basisEl_Id] + \
                   [ basisProductMatrix(err,sparse) for err in loc_noise_errinds]
        errbasis = _Basis(matrices=errbasis, sparse=sparse) #single element basis (plus identity)
        
        #Construct one embedded Lindblad-gate using all `errbasis` terms
        ssLocQ = [tuple(['Q%d'%i for i in range(nLocal)])]
        basisLocQ = _Basis('pp', 2**nLocal, sparse=sparse)
        locId = _sps.identity(4**nLocal,'d','csr') if sparse else _np.identity(4**nLocal,'d')
        localErr = Lindblad(locId, ham_basis=errbasis,
                            nonham_basis=errbasis, cptp=True,
                            nonham_diagonal_only=True, truncate=True,
                            mxBasis=basisLocQ)
        fullLocalErr = Embedded(ssAllQ, ['Q%d'%i for i in all_possible_err_qubit_inds],
                                localErr, basisAllQ.dim)
        printer.log("Lindblad gate w/dim=%d and %d params (from error basis of len %d) -> embedded to gate w/dim=%d" %
                    (localErr.dim, localErr.num_params(), len(errbasis), fullLocalErr.dim),2)

        
    elif loc_noise_type == "manylittle": 
        # make a composed-gate of embedded single-basis-element Lindblad-gates,
        #  one for each specified error term  
            
        loc_noise_termgates = [] #list of gates to compose
        
        for wt, maxHops in weight_maxhops_tuples:
                
            ## loc_noise_errinds = [] # list of basis indices for all local-error terms 
            possible_err_qubit_inds = _np.array(qubitGraph.radius(target_qubit_inds, maxHops),'i') # we know node labels are integers
            nPossible = len(possible_err_qubit_inds) # also == "nLocal" in this case
            basisEl_Id = basisProductMatrix(_np.zeros(wt,'i'),sparse) #identity basis el

            wtId = _sps.identity(4**wt,'d','csr') if sparse else _np.identity(4**wt,'d')
            wtBasis = _Basis('pp', 2**wt, sparse=sparse)

            printer.log("Weight %d, max-hops %d: %d possible qubits" % (wt,maxHops,nPossible),3)
            
            for err_qubit_local_inds in _itertools.combinations(list(range(nPossible)), wt):
                # err_qubit_inds are in range [0,nPossible-1] qubit indices
                #Future: check that err_qubit_inds marks qubits that are connected

                errbasis = [basisEl_Id]
                for err_basis_inds in _iter_basis_inds(wt):  
                    error = _np.array(err_basis_inds,'i') #length == wt
                    basisEl = basisProductMatrix(error, sparse)
                    errbasis.append(basisEl)

                err_qubit_global_inds = possible_err_qubit_inds[list(err_qubit_local_inds)]
                printer.log("Error on qubits %s -> error basis of length %d" % (err_qubit_global_inds,len(errbasis)), 4)
                errbasis = _Basis(matrices=errbasis, sparse=sparse) #single element basis (plus identity)
                termErr = Lindblad(wtId, ham_basis=errbasis,
                                   nonham_basis=errbasis, cptp=True,
                                   nonham_diagonal_only=True, truncate=True,
                                   mxBasis=wtBasis)
        
                fullTermErr = Embedded(ssAllQ, ['Q%d'%i for i in err_qubit_global_inds],
                                       termErr, basisAllQ.dim)
                assert(fullTermErr.num_params() == termErr.num_params())
                printer.log("Lindblad gate w/dim=%d and %d params -> embedded to gate w/dim=%d" %
                            (termErr.dim, termErr.num_params(), fullTermErr.dim))
                
                loc_noise_termgates.append( fullTermErr )
              
        fullLocalErr = Composed(loc_noise_termgates)    
        
    else:
        raise ValueError("Invalid `loc_noise_type` arguemnt: %s" % loc_noise_type)
        
    if fullIdleErr is not None:
        return Composed([fullTargetOp,fullIdleErr,fullLocalErr])
    else:
        return Composed([fullTargetOp,fullLocalErr])



# -----------------------------------------------------------------------------------
#  nqnoise gate sequence construction methods
# -----------------------------------------------------------------------------------

#Note: these methods assume a GateSet with:
# Gx and Gy gates on each qubit that are pi/2 rotations
# a prep labeled "rho0"
# a povm labeled "Mdefault" - so effects labeled "Mdefault_N" for N=0->2^nQubits-1


def _onqubit(s,iQubit):
    """ Takes `s`, a tuple of gate *names* and creates a GateString
        where those names act on the `iQubit`-th qubit """
    return _objs.GateString( [_Lbl(nm,iQubit) for nm in s])

def find_amped_polys_for_syntheticidle(qubit_filter, idleStr, gateset, singleQfiducials=None,
                                       prepLbl=None, effectLbls=None, initJ=None, initJrank=None,
                                       wrtParams=None):
    """
    TODO: docstring
    prepLbl : Label
    effectLbls : list of Labels
    singleQfiducials : list of gate-name-string 1-qubit fiducial sequences
    idle_fidpairs: list of (prep,meas) fiducial pairs (each a GateString) designed to 
         probe an operation that has some maximal weight error (that idleStr is known to have fewer than)
    """
    #TODO: Assert that gateset uses termorder:1, as doing L1-L0 to extract the "amplified" part
    # relies on only expanding to *first* order.
    
    if prepLbl is None:
        prepLbl = list(gateset.preps.keys())[0]
    if effectLbls is None:
        povmLbl = list(gateset.povms.keys())[0]
        effectLbls = [ _Lbl("%s_%s" % (povmLbl,l)) for l in gateset.povms[povmLbl] ]
    if singleQfiducials is None:
        # TODO: assert gate set has Gx and Gy gates?
        singleQfiducials = [(), ('Gx',), ('Gy',)] # ('Gx','Gx')
        
    #dummy = 0.05*_np.ones(gateset.num_params(),'d') # for evaluating derivs...
    #dummy = 0.05*_np.arange(1,gateset.num_params()+1) # for evaluating derivs...
    dummy = 0.05*_np.random.random(gateset.num_params()) 
     # expect terms to be either coeff*x or coeff*x^2 - (b/c of latter case don't eval at zero)
    
    #amped_polys = []
    selected_gatename_fidpair_lists = []
    if wrtParams is None: wrtParams = slice(0,gateset.num_params())
    Np = _slct.length(wrtParams) 
    if initJ is None:
        J = _np.empty( (0,Np), 'complex'); Jrank = 0
    else:
        J = initJ; Jrank = initJrank
    
     #loop over all possible fiducial pairs
    nQubits = len(qubit_filter)
    for prep in _itertools.product(*([singleQfiducials]*nQubits) ):
        prepFid = _objs.GateString(())
        for i,el in enumerate(prep):
            prepFid = prepFid + _onqubit(el,qubit_filter[i])
            
        for meas in _itertools.product(*([singleQfiducials]*nQubits) ):
            measFid = _objs.GateString(())
            for i,el in enumerate(meas):
                measFid = measFid + _onqubit(el,qubit_filter[i])
    
            gstr_L0 = prepFid + measFid            # should be a GateString
            gstr_L1 = prepFid + idleStr + measFid  # should be a GateString
            ps=gateset._calc().prs_as_polys(prepLbl, effectLbls, gstr_L1 )
            qs=gateset._calc().prs_as_polys(prepLbl, effectLbls, gstr_L0 )
            #OLD: Jtest = J
            for elbl,p,q in zip(effectLbls,ps,qs):
                amped = p + -1*q # the amplified poly
                Jrow = _np.array([[ amped.deriv(iParam).evaluate(dummy) for iParam in _slct.as_array(wrtParams)]])
                Jtest = _np.concatenate((J,Jrow),axis=0) 
                testRank = _np.linalg.matrix_rank(Jtest)
                #print("find_amped_polys_for_syntheticidle: ",prep,meas,elbl," => rank ",testRank, " (Np=",Np,")")
                if testRank > Jrank:
                    #print("taken!")
                    J = Jtest
                    Jrank = testRank
                    #amped_polys.append(amped)
                    gatename_fidpair_list = [ (prep[i],meas[i]) for i in range(nQubits) ]
                    selected_gatename_fidpair_lists.append( gatename_fidpair_list )
                    #OLD selected_fidpairs.append( (prepFid, measFid) )
                    if Jrank == Np: break # this is the largest rank J can take!
    
    #DEBUG
    #print("DB: J = ")
    #_gt.print_mx(J)
    #print("DB: svals of J for synthetic idle: ", _np.linalg.svd(J, compute_uv=False))
    
    return J, Jrank, selected_gatename_fidpair_lists

def get_fidpairs_needed_to_access_amped_polys(qubit_filter, germPowerStr, amped_polyJ, gateset,
                                              singleQfiducials=None, prepLbl=None, effectLbls=None,
                                              wrtParams=None):
    """
    TODO: docstring
    """
    if prepLbl is None:
        prepLbl = list(gateset.preps.keys())[0]
    if effectLbls is None:
        povmLbl = list(gateset.povms.keys())[0]
        effectLbls = list(gateset.povms[povmLbl].keys())
    if singleQfiducials is None:
        # TODO: assert gate set has Gx and Gy gates?
        singleQfiducials = [(), ('Gx',), ('Gy',)] # ('Gx','Gx')
        
    #dummy = 0.05*_np.ones(gateset.num_params(),'d') # for evaluating derivs...
    #dummy = 0.05*_np.arange(1,gateset.num_params()+1) # for evaluating derivs...
    dummy = 0.05*_np.random.random(gateset.num_params()) 
     # expect terms to be either coeff*x or coeff*x^2 - (b/c of latter case don't eval at zero)
    
    #OLD: selected_fidpairs = []
    gatename_fidpair_lists = []
    if wrtParams is None: wrtParams = slice(0,gateset.num_params())
    Np = _slct.length(wrtParams) 
    Namped = amped_polyJ.shape[0]; assert(amped_polyJ.shape[1] == Np)
    J = _np.empty( (0,Namped), 'complex'); Jrank = 0
    
    #loop over all possible fiducial pairs
    nQubits = len(qubit_filter)
    for prep in _itertools.product(*([singleQfiducials]*nQubits) ):
        prepFid = _objs.GateString(())
        for i,el in enumerate(prep):
            prepFid = prepFid + _onqubit(el,qubit_filter[i])
            
        for meas in _itertools.product(*([singleQfiducials]*nQubits) ):
            measFid = _objs.GateString(())
            for i,el in enumerate(meas):
                measFid = measFid + _onqubit(el,qubit_filter[i])
     
            gstr = prepFid + germPowerStr + measFid  # should be a GateString
            ps=gateset._calc().prs_as_polys(prepLbl, effectLbls, gstr)
            #OLD: Jtest = J
            for elbl,p in zip(effectLbls,ps):
                #For each fiducial pair (included pre/effect), determine how the
                # (polynomial) probability relates to the *amplified* directions 
                # (also polynomials - now encoded by a "Jac" row/vec)
                prow = _np.array([ p.deriv(iParam).evaluate(dummy) for iParam in _slct.as_array(wrtParams)]) # complex
                Jrow = _np.array([[ _np.vdot(prow,amped_row) for amped_row in amped_polyJ]]) # complex
                Jtest = _np.concatenate((J,Jrow),axis=0)  
                testRank = _np.linalg.matrix_rank(Jtest)
                if testRank > Jrank:
                    #print("ACCESS: ",prep,meas,testRank)
                    J = Jtest
                    Jrank = testRank
                    gatename_fidpair_lists.append([ (prep[i],meas[i]) for i in range(nQubits) ])
                    #OLD selected_fidpairs.append( (prepFid, measFid) )
                    if Jrank == Namped: # then we've selected enough pairs to access all of the amplified directions
                        return gatename_fidpair_lists # (i.e. the rows of `amped_polyJ`)
                        
     
    #DEBUG
    #print("DEBUG: J = ")
    #_gt.print_mx(J)
    #print("Nullspace = ")
    #_gt.print_mx(pygsti.tools.nullspace(J))
    raise ValueError(("Could not find sufficient fiducial pairs to access "
                      "all the amplified diretions - only %d of %d were accessible")
                     % (Jrank,Namped))
    
    
def tile_idle_fidpairs(nQubits, idle_gatename_fidpair_lists, maxIdleWeight):
    """
    TODO: docstring
    """

    # "Tile w/overlap" the fidpairs for a k-qubit subset (where k == maxIdleWeight)
    
    # we want to create a k-coverage set of length-nQubits strings/lists containing
    # the elements 012..(k-1)(giving the "fiducial" - possible a gate sequence - for
    # each qubit) such that for any k qubits the set includes string where these qubits
    # take on all the fiducial pairs given in the idle fiducial pairs
    
    # Each element of idle_gatename_fidpair_lists is a "gatename_fidpair_list". 
    # Each "gatename_fidpair_list" is a list of k (prep-gate-name-str, meas-gate-name-str)
    # tuples, one per *qubit*, giving the gate names to perform on *that* qubit.
    
    #OLD - we don't need this conversion since we can take the gatename_fidpair_lists as an arg.
    # XX idle_fidpairs elements are (prepStr, measStr) on qubits 0->(k-1); to convert each
    # XX element to a list of k (prep-gate-name-str, meas-gate-name-str) tuples one per *qubit*.
    
    tmpl = get_kcoverage_template(nQubits, maxIdleWeight)
    final_fidpairs = []
    
    for gatename_fidpair_list in idle_gatename_fidpair_lists:
        # replace 0..(k-1) in each template string with the corresponding
        # gatename_fidpair (acts on the single qubit identified by the
        # its index within the template string), then convert to a GateString/Circuit
        tmpl_instance = [ [gatename_fidpair_list[i] for i in tmpl_row]  for tmpl_row in tmpl ]
        for tmpl_instance_row in tmpl_instance: 
            # tmpl_instance_row row is nQubits long; elements give the 
            # gate *names* to perform on that qubit.
            prep_gates = []
            meas_gates = []
            for iQubit,gatename_fidpair in enumerate(tmpl_instance_row):
                prep_gatenames, meas_gatenames = gatename_fidpair
                prep_gates.extend( [_Lbl(gatename,iQubit) for gatename in prep_gatenames ]) 
                meas_gates.extend( [_Lbl(gatename,iQubit) for gatename in meas_gatenames ]) 
                final_fidpairs.append( (_objs.GateString(prep_gates),
                                        _objs.GateString(meas_gates)) )
            
    _lt.remove_duplicates_in_place(final_fidpairs)    
    return final_fidpairs
    
def tile_cloud_fidpairs(gatename_fidpair_lists, germPower, L, germ, cloudbank):
    """
    TODO: docstring
    """    
    #Note: assume fidpairs and germPower are for the qubits in the cloudbank[0] cloud
    base_cloud = cloudbank[0]
    unused_clouds = list(cloudbank)
    base_qubits = base_cloud['qubits']
    base_qubit_index = { ql: i for i,ql in enumerate(base_qubits) } # keys = qubit labels
    sequences = []
    germs = []
    
    while(len(unused_clouds) > 0):
        
        #figure out what clouds can be processed in parallel
        parallel_clouds = [unused_clouds[0]]
        parallel_qubits = set(unused_clouds[0]['qubits']) # qubits used by parallel_clouds
        del unused_clouds[0]
        
        to_delete = []
        for i,cloud in enumerate(unused_clouds):
            if len(parallel_qubits.intersection(cloud['qubits'])) == 0:
                parallel_qubits.add(cloud['qubits'])
                parallel_clouds.append(cloud)
                to_delete.append(i)
        for i in reversed(to_delete):
            del unused_clouds[i]
            
        #Create gate sequence "info-tuples" by processing in parallel the
        # list of parallel_clouds 
        for gatename_fidpair_list in gatename_fidpair_lists:
            prepStr = []
            measStr = []
            germStr = []
            germPowerStr = []
            for cloud in parallel_clouds:
                for base_ql_index,cloud_ql in enumerate(cloud['qubits']): 
                    prep,meas = gatename_fidpair_list[base_ql_index] # gate-name lists
                    prepStr.extend( [_Lbl(name,cloud_ql) for name in prep] )
                    measStr.extend( [_Lbl(name,cloud_ql) for name in meas] )
                
                germStr.extend([ _Lbl(gl.name,
                                [ cloud['qubits'][base_qubit_index[ql]] for ql in gl.sslbls] )
                                for gl in germ ] )
                germPowerStr.extend([ _Lbl(gl.name,
                                    [ cloud['qubits'][base_qubit_index[ql]] for ql in gl.sslbls] )
                                    for gl in germPower ] ) 
            germs.append( _objs.GateString(germStr) )
            sequences.append( (_objs.GateString(prepStr + germPowerStr + measStr), L, germs[-1], "XX", "XX") )
              # gatestring, L, germ, prepFidIndex, measFidIndex??
        
    # return a list of gate strings (duplicates removed)
    return _lt.remove_duplicates(sequences), _lt.remove_duplicates(germs)        
  
    
def to_synthetic_idle(gateset, germStr, nqubits, core_qubits):
    """
    TODO: docstring
    Returns germStr repeated to that it forms an idle operation
    """
    # First, get a dense representation of germStr on core_qubits
    # Note: only works with one level of embedding...
    def extract_gate(g):
        """ Get the gate action as a dense gate on core_qubits """
        if isinstance(g, _objs.EmbeddedGateMap):
            assert(len(g.stateSpaceLabels.labels) == 1) # 1 tensor product block
            assert(len(g.stateSpaceLabels.labels[0]) == nqubits) # expected qubit count
            qubit_labels = g.stateSpaceLabels.labels[0]
            
            # for now - assume we know the form of qubit_labels
            assert(list(qubit_labels) == [('Q%d'%i) for i in range(nqubits)] or 
                   list(qubit_labels) == [ i for i in range(nqubits)]) 
            new_qubit_labels = []
            for core_ql in core_qubits:
                if core_ql in qubit_labels: new_qubit_labels.append(core_ql) # same convention!
                elif ("Q%d" % core_ql) in qubit_labels: new_qubit_labels.append("Q%d" % core_ql) # HACK!
            ssl = _StateSpaceLabels(new_qubit_labels)
            #DEBUG print("qubit_labels = ", qubit_labels, " new_qubit_labels = ",new_qubit_labels, "targets = ",g.targetLabels)
            assert(all([(tgt in new_qubit_labels) for tgt in g.targetLabels])) # all target qubits should be kept!
            if len(new_qubit_labels) == len(g.targetLabels): 
                # embedded gate acts on entire core-qubit space:
                return g.embedded_gate
            else:                
                return _objs.EmbeddedGate(ssl, g.targetLabels, g.embedded_gate)
        
        elif isinstance(g, _objs.ComposedGateMap):
            return _objs.ComposedGate([extract_gate(f) for f in g.factorgates])
        else:
            raise ValueError("Cannot extract core contrib from %s" % str(type(g)))
        
    core_dim = 4**len(core_qubits)
    product = _np.identity(core_dim, 'd')
    core_gates = {}
    for gl in germStr:
        if gl not in core_gates:
            core_gates[gl] = extract_gate(gateset.gates[gl])
        product = _np.dot(core_gates[gl], product)
    
    # Then just do matrix products until we hit the identity (or a large order)
    reps = 1; target = _np.identity(core_dim,'d')
    repeated = product
    while(_np.linalg.norm(repeated - target) > 1e-6 and reps < 20): # HARDCODED MAX_REPS
        repeated = _np.dot(repeated, product); reps += 1
        
    return germStr*reps

def get_candidates_for_core(gateset, core_qubits, candidate_counts, seedStart): # or for cloud - so we can check that gates for all "equivalent" clouds exist?
    """
    TODO: docstring
    """

    # collect gates that only act on core_qubits.
    gatelabel_list = []; full_core_list = []
    for gl in gateset.gates.keys():
        if gl.sslbls is None: continue # gates that act on everything (usually just the identity Gi gate)
        if set(gl.sslbls).issubset(core_qubits):
            gatelabel_list.append(gl)
        if set(gl.sslbls) == set(core_qubits):
            full_core_list.append(gl)
        
    # form all low-length strings out of these gates.
    candidate_germs = []
    for i,(germLength, count) in enumerate(candidate_counts.items()):
        if count == "all upto":
            candidate_germs.extend( _gsc.list_all_gatestrings_without_powers_and_cycles(
                    gatelabel_list, maxLength=germLength) )
        else:
            candidate_germs.extend( _gsc.list_random_gatestrings_onelen(
                    gatelabel_list, germLength, count, seed=seedStart+i))
    
    candidate_germs = [ g for g in candidate_germs if any([(gl in g) for gl in full_core_list]) ] # filter?
    return candidate_germs

def create_nqubit_sequences(nQubits, maxLengths, geometry, cloudbanks, maxIdleWeight=1, maxhops=0,
                          extraWeight1Hops=0, extraGateWeight=0, sparse=False, verbosity=0):
    """ 
    TODO: docstring

    cloudbanks == list of "cloudsbanks"
    cloudbank = list of *equivalent* (by-translation) clouds
    cloud = dict w/ 'qubits' and 'core' keys that are lists/tuples of integers giving 
        the indices of all the qubits in the cloud and the subset of "core" qubits 
    
    """
    
    # e.g. in a chain of 5 qubits clouds could be:
    # [{'qubits': [0,1,2], 'core': [1]}, {'qubits': [1,2,3], 'core': [2]}, ... ] OR
    # [{'qubits': [0,1,2,3], 'core': [1,2]}, ...]  -- then do candidate germ selection
    #  on the *first* could in the set of "equivalent" clouds and tiling does find/replace to other clouds,
    #  eventually allowing overlapping non-cores, but at first just keep parallel clouds disjoint.
    #base_clouds = XXX # an arg, or from qubitGraph eventually?
    
    #Maybe something like this: ??
    #core_qubits, cloud_qubits = get_cloudbanks(qubitGraph, maxhops,
    #                                           extraWeight1Hops, extraGateWeight) # get the "local" qubits of candidate_germ
    
    printer = _VerbosityPrinter.build_printer(verbosity)
    printer.log("Creating full gateset")
    gateset = build_nqnoise_gateset(nQubits, geometry, maxIdleWeight, maxhops,
                                    extraWeight1Hops, extraGateWeight, sparse, verbosity=printer-5,
                                    sim_type="termorder:1", parameterization="H+S terms")
    ideal_gateset = build_nqnoise_gateset(nQubits, geometry, 0, 0,
                                          0, 0, False, verbosity=printer-5,
                                          sim_type="map", parameterization="H+S") # for testing for synthetic idles
    #print("DB: gateset state space labels = ", gateset.stateSpaceLabels)
    sequences = []
    
    Np = gateset.num_params()
    idleGateStr = _objs.GateString(("Gi",))
    singleQfiducials = [(), ('Gx',), ('Gy',)] # , ('Gx','Gx')
    prepLbl = _Lbl("rho0")
    effectLbls = [ _Lbl("Mdefault_%s" % l) for l in gateset.povms['Mdefault'].keys()]
    
    # create a gateset with maxIdleWeight qubits that includes all
    # the errors of the actual n-qubit gateset...
    #Note: I don't think geometry matters here, since we just look at the idle gate.
    printer.log("Creating \"idle error\" gateset on %d qubits" % maxIdleWeight)
    idle_gateset = build_nqnoise_gateset(maxIdleWeight, geometry, maxIdleWeight, maxhops,
                                         extraWeight1Hops, extraGateWeight, sparse, verbosity=printer-5,
                                         sim_type="termorder:1", parameterization="H+S terms")
    
    #First get "idle germ" sequences since the idle is special
    printer.log("Getting sequences needed for max-weight=%d errors on the idle gate" % maxIdleWeight)
    ampedJ, ampedJ_rank, idle_maxwt_gatename_fidpair_lists = find_amped_polys_for_syntheticidle(
        list(range(maxIdleWeight)), idleGateStr, idle_gateset, singleQfiducials, prepLbl, None)
    
    #Since this is the idle, these maxIdleWeight-qubit fidpairs can be "tiled"
    # to the n-qubits
    printer.log("%d \"idle template pairs\".  Tiling these to all %d qubits" % 
                (len(idle_maxwt_gatename_fidpair_lists), nQubits),2)
    idle_fidpairs = tile_idle_fidpairs(nQubits, idle_maxwt_gatename_fidpair_lists, maxIdleWeight)
    printer.log("%d idle pairs found" % len(idle_fidpairs),2)
                
    # Create idle sequences by sandwiching Gi^L between all idle fiducial pairs
    selected_germs = [ idleGateStr ]
    for L in maxLengths:
        for fidpair in idle_fidpairs:
            prepFid, measFid = fidpair
            sequences.append( (prepFid + idleGateStr*L + measFid, L, idleGateStr, "XX", "XX") ) # gatestring, L, germ, prepFidIndex, measFidIndex??
    printer.log("%d idle sequences (for all max-lengths: %s)" % (len(sequences), str(maxLengths)))
        
    #Look for and add additional germs to amplify the *rest* of the gateset's parameters
    Gi_nparams = gateset.gates['Gi'].num_params()
    SPAM_nparams = sum([obj.num_params() for obj in _itertools.chain(gateset.preps.values(), gateset.povms.values())])
    Np_to_amplify = gateset.num_params() - Gi_nparams - SPAM_nparams
    printer.log("Idle gate has %d (amplified) params; Spam has %d (unamplifiable) params; %d gate params left" %
               (Gi_nparams, SPAM_nparams, Np_to_amplify))

    #OLD
    ##ASSUME: that the gateset is constructed such that SPAM and Gi params are first (and independent from)
    ## "pure gate" params, so we can get offset to the "pure gate" params by looking at the max Gi param index+1
    #gate_param_offset = max(_slct.as_array(gateset.gates['Gi'].gpindices))+1
    #Ngp = Np - gate_param_offset # number of "pure gate" params that we want to amplify
    #wrtParams = slice(gate_param_offset,Np) # the parameters we want to amplify (diff with respect to)
    #J = _np.empty( (0,Ngp), 'complex'); Jrank = 0
    ##print("DB: Ngp = ",Ngp," offset = ",gate_param_offset)
    
    printer.log("Beginning search for non-idle germs & fiducial pairs")
    for icb,cloudbank in enumerate(cloudbanks):
        
        # different "clouds" - each consisting of a set of representative "cloud" &"core" qubits
        # - AND how this cloud can be repeated?
        base_cloud = cloudbank[0] # pick the first as the representative one
        core_qubits = base_cloud['core']
        cloud_qubits = base_cloud['qubits']

        # Collect "pure gate" params of gates that *exactly* on (just and only) the core_qubits;
        # these are the parameters we want this cloud to amplify.  If all the gates which act on
        # the core act on the entire core (when there are no gates that only act on only a part
        # of the core), then these params will be the *only* ones the choosen germs will amplify.
        # But, if there are partial-core gates, the germs might amplify some of their parameters
        # (e.g. Gx:0 params might get amplified when processing a cloud whose core is [0,1]).
        # This is fine, but we don't demand that such params be amplified, since they *must* be
        # amplified for another cloud with core exaclty equal to the gate's target qubits (e.g. [0])
        wrtParams = set()
        Gi_params = set(_slct.as_array(gateset.gates['Gi'].gpindices))
        for gl in gateset.gates.keys():
            if gl.sslbls is None: continue # gates that act on everything (usually just the identity Gi gate)
            if set(gl.sslbls) == set(core_qubits):
                wrtParams.update( _slct.as_array(gateset.gates[gl].gpindices) )
        pure_gate_params = wrtParams - Gi_params # (Gi params don't count)
        wrtParams = _slct.list_to_slice( sorted(list(pure_gate_params)), array_ok=True )
        Ngp = _slct.length(wrtParams) # number of "pure gate" params that we want to amplify
                
        J = _np.empty( (0,Ngp), 'complex'); Jrank = 0
        
        printer.log("Cloudbank %d of %d: base qubits = %s, core = %s, params(single-cloud,total-bank)= %d,%d" % 
                    (icb+1,len(cloudbanks),str(cloud_qubits), str(core_qubits), Ngp, Ngp*len(cloudbank)),2)
        
        candidate_counts = {4: 'all upto', 5: 10, 6: 10 } # should be an arg? HARDCODED!
        candidate_germs = get_candidates_for_core(gateset, core_qubits, candidate_counts, seedStart=1234)
          # candidate_germs should only use gates with support on *core* qubits?
            
        for candidate_germ in candidate_germs:
            printer.log("Candidate germ: %s" % str(candidate_germ),3)

            #Let's see if we want to add this germ
            syntheticIdle = to_synthetic_idle(ideal_gateset, candidate_germ, nQubits, core_qubits) 
            printer.log("Corresponding synthetic idle: %s" % str(syntheticIdle),3)
            J, Jrank, selected_pairs = find_amped_polys_for_syntheticidle(
                cloud_qubits, syntheticIdle, gateset, singleQfiducials, prepLbl, effectLbls, J, Jrank, wrtParams)
            
            nNewAmpedDirs = len(selected_pairs)
            if nNewAmpedDirs > 0: # then there are some "directions" that this germ amplifies that previous ones didn't...
                printer.log("Germ amplifies %d additional parameters (so %d of %d amplified for this base cloud)" %
                            (nNewAmpedDirs, Jrank, Ngp), 3) # assume each cloud amplifies an independent set of params
                #OLD selected_germs.append(candidate_germ)
                amped_polyJ = J[-nNewAmpedDirs:, :] # just the rows of the Jacobian corresponding to
                                                    # the directions we want the current germ to amplify
                #print("DB: amped_polyJ svals = ",_np.linalg.svd(amped_polyJ, compute_uv=False))
                
                #Figure out which fiducial pairs access the amplified directions at each value of L
                add_germs = True # only add germs on the first L-value (since they won't depend on L) 
                for L in maxLengths:
                    # from gatestringconstruction.py
                    reps = _gsc.repeat_count_with_max_length(candidate_germ,L)
                    if reps == 0: continue # don't process when we don't use the germ at all...
                    printer.log("Finding the fiducial pairs needed to amplify %s^%d (L=%d)" %
                               (str(candidate_germ),reps,L),4)
                    
                    germPower = candidate_germ * reps # germ^reps  
                    gatename_fidpair_lists = get_fidpairs_needed_to_access_amped_polys(
                        cloud_qubits, germPower, amped_polyJ,
                        gateset, singleQfiducials, prepLbl, effectLbls, wrtParams)
                    printer.log("Found %d fiducial pairs" % len(gatename_fidpair_lists),4)
                    #Now we have `fidpairs` that are n-qubit fiducial pairs but which only have gates on `cloud_qubits`
                    # Next, we need to "tile" these sequences so they act on multiple "clouds" in parallel so
                    # we use all the qubits.
                    
                    addl_seqs, addl_germs = tile_cloud_fidpairs(gatename_fidpair_lists, germPower, L, candidate_germ, cloudbank)
                    sequences.extend(addl_seqs)
                    if add_germs: # addl_germs is independent of L - so just add once
                        selected_germs.extend(addl_germs)
                        add_germs = False
                        
                    printer.log("After tiling to cloudbank, have %d sequences, %d germs" % (len(sequences),len(selected_germs)),4)
                
                if Jrank == Np: # really this will never happen b/c we'll never amplify SPAM and gauge directions...
                    break       # instead exit after we haven't seen a germ that amplifies anything new in a while                
                
                consecutive_unhelpful_germs = 0
            else:
                consecutive_unhelpful_germs += 1
                printer.log(("No additional amplified params: %d consecutive unhelpful germs." % consecutive_unhelpful_germs), 3)
                if consecutive_unhelpful_germs == 5: # ??
                    #print("DB: J = ")
                    #_gt.print_mx(J[:,24:])
                    #print("Nullspace = ")
                    #_gt.print_mx(_mt.nullspace(J[:,24:]))
                    break # next cloudbank
                
    printer.log("Done: %d sequences, %d germs" % (len(sequences),len(selected_germs)))
    return sequences, selected_germs
                
import numpy as _np
import itertools as _itertools

def get_kcoverage_template(n, k, debug=0):
    """ TODO: docstring """
    #n = total number of qubits
    #indices run 0->(k-1)
    assert(n >= k), "Total number of qubits must be >= k"
    
    #first k cols -> k! permutations of the k indices: 
    cols = [ list() for i in range(k) ]
    for row in _itertools.permutations(range(k),k):
        for i in range(k): 
            cols[i].append(row[i])
    nRows = len(cols[0])
    if debug > 0: print("get_template(n=%d,k=%d):" % (n,k))

    # Now add cols k to n-1:
    for a in range(k,n): # a is index of column we're adding
        if debug > 1: print(" - Adding column %d: currently %d rows" % (a,nRows))
        
        #We know that columns 0..(a-1) satisfy the property that
        # the values of any k of them contain at every permutation 
        # of the integers 0..(k-1) (perhaps multiple times).  It is
        # then also true that the values of any (k-1) columns take
        # on each Perm(k,k-1) - i.e. the length-(k-1) permutations of
        # the first k integers.
        #
        # So at this point we consider all combinations of k columns
        # that include the a-th one (so really just combinations of
        # k-1 existing colums), and fill in the a-th column values 
        # so that the k-columns take on each permuations of k integers.
        # 
        
        col_a = [None]*nRows # the new column - start with None sentinels in all current rows
        
        for existing_cols in _itertools.combinations(range(a),k-1):
            if debug > 2: print("  - check perms are present for cols %s" % str(existing_cols + (a,)) )
            
            #make sure cols existing_cols + [a] take on all the needed permutations
            # Since existing_cols already takes on all permuations minus the last
            # value (which is determined as it's the only one missing from the k-1
            # existing cols) - we just need to *complete* each existing row and possibly
            # duplicate + add rows to ensure all completions exist. 
            for desired_row in _itertools.permutations(range(k),k):
                                
                matching_rows = [] # rows that match desired_row on existing_cols
                open_rows = [] # rows with a-th column open (unassigned)
                
                for m in range(nRows):
                    if all([ cols[existing_cols[i]][m] == desired_row[i] for i in range(k-1)]):
                        # m-th row matches desired_row on existing_cols
                        matching_rows.append(m)
                    if col_a[m] is None:
                        open_rows.append(m)
                
                if debug > 3: print("   - perm %s: %d rows, %d match perm, %d open"
                                % (str(desired_row), nRows, len(matching_rows), len(open_rows)) )
                v = {'value': desired_row[k-1], 'alternate_rows': matching_rows}
                for m in matching_rows:
                    if col_a[m] is None: # slot is open - take it!
                        if debug > 3: print("    -> open row (index %d) matches!" % m)
                        col_a[m] = v; break
                else: # no open slots
                    # option1: (if there are any open rows)
                    #  Look to swap an existing value in a matching row 
                    #   to an open row allowing us to complete the matching
                    #   row using the current desired_row.
                    open_rows = set(open_rows) # b/c use intersection below
                    shift_soln_found = False
                    if len(open_rows) > 0:
                        for m in matching_rows:
                            # can assume col_a[m] is *not* None given above logic
                            ist = open_rows.intersection(col_a[m]['alternate_rows'])
                            if len(ist) > 0:
                                m2 = ist.pop() # just get the first element
                                # move value in row m to m2, then put v into the now-open m-th row
                                col_a[m2] = col_a[m]
                                col_a[m] = v
                                if debug > 3: print("    -> row %d >> row %d, and row %d matches!" % (m,m2,m))
                                shift_soln_found = True
                                break
                                
                    if shift_soln_found == False:
                        # no shifting can be performed to place v into an open row,
                        # so we just create a new row equal to desired_row on existing_cols.
                        # How do we choose the non-(existing & last) colums? For now, just
                        # replicate the first element of matching_rows:
                        if debug > 3: print("    -> creating NEW row.")
                        for i in range(a):
                            cols[i].append( cols[i][matching_rows[0]] )
                        col_a.append(v)
                        nRows += 1
                        
        # a-th column is complete; "cement" it by replacing 
        # value/alternative_rows dicts with just the values
        col_a = [ d['value'] for d in col_a ]
        cols.append(col_a)    
                
    #convert cols to "strings" (rows)
    assert(len(cols) == n)
    rows = []
    for i in range(len(cols[0])):
        rows.append( [ cols[j][i] for j in range(n)] )
        
    if debug > 0: print(" Done: %d rows total" % len(rows))
    return rows
        

def check_kcoverage_template(rows, n, k, debug=0):
    """ TODO: docstring """
    if debug > 0: print("check_template(n=%d,k=%d)" % (n,k))
    
    #for each set of k qubits (of the total n qubits)
    for cols_to_check in _itertools.combinations(range(n),k):
        if debug > 1: print(" - checking cols %s" % str(cols_to_check))
        for perm in _itertools.permutations(range(k),k):
            for m,row in enumerate(rows):
                if all([ row[i] == perm[i] for i in range(k) ]):
                    if debug > 2: print("  - perm %s: found at row %d" % (str(perm),m))
                    break
            else:
                assert(False),                     "Permutation %s on qubits (cols) %s is not present!" % (str(perm),str(cols_to_check))
    if debug > 0: print(" check succeeded!")                                                             
    