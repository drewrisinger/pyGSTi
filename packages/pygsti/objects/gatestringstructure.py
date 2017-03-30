from __future__ import division, print_function, absolute_import, unicode_literals
#*****************************************************************
#    pyGSTi 0.9:  Copyright 2015 Sandia Corporation
#    This Software is released under the GPL license detailed
#    in the file "license.txt" in the top-level pyGSTi directory
#*****************************************************************
""" Defines the GatestringStructure class and supporting functionality."""

import collections as _collections
from ..tools import listtools as _lt

class GatestringStructure(object):
    def __init__(self, xvals, yvals, prepStrs, effectStrs, xy_gatestring_dict,
                 fidpair_filters, gatestring_filters, gatelabel_aliases):

        self.xvals = xvals
        self.yvals = yvals
        self.prepStrs = prepStrs
        self.effectStrs = effectStrs
        self.gsDict = xy_gatestring_dict
        self.fidpair_filters = fidpair_filters
        self.gatestring_filters = gatestring_filters
        self.aliases = gatelabel_aliases

        self.used_xvals = [ x for x in xvals if any([ (self.gsDict[(x,y)] is not None) for y in yvals]) ]
        self.used_yvals = [ y for y in yvals if any([ (self.gsDict[(x,y)] is not None) for x in xvals]) ]

    def get_fidpair_filter(self, x,y):
        return self.fidpair_filters[(x,y)] if (self.fidpair_filters is not None) else None

    def get_gatestring_filter(self,x,y):
        return self.gatestring_filters[(x,y)] if (self.gatestring_filters is not None) else None


    

class LsGermsStructure(GatestringStructure):

    def __init__(self, Ls, germs, prepStrs, effectStrs, truncFn,
                 fidPairs=None, gatestring_lists=None, gatelabel_aliases=None):

        if fidPairs is None:
            fidpair_filters = None
        elif isinstance(fidPairs,dict) or hasattr(fidPairs,"keys"):
            #Assume fidPairs is a dict indexed by germ
            fidpair_filters = { (x,y): fidPairs[y] 
                                for x in Ls for y in germs }
        else:
            #Assume fidPairs is a list
            fidpair_filters = { (x,y): fidPairs
                                for x in Ls for y in germs }

        if gatestring_lists is not None:
            gstr_filters = { (x,y) : gatestring_lists[i]
                             for i,x in enumerate(Ls)
                             for y in germs }            
        else:
            gstr_filters = None

               
        remove_dups = True
        #if remove_dups == True, remove duplicates in
        #  L_germ_tuple_to_baseStr_dict by replacing with None
        fullDict = _collections.OrderedDict(
            [ ( (L,germ), truncFn(germ,L) )
              for L in Ls for germ in germs] )
        self.truncFn = truncFn

        baseStr_dict = _collections.OrderedDict()

        tmpRunningList = []
        for L in Ls:
            for germ in germs:
                if remove_dups and fullDict[(L,germ)] in tmpRunningList:
                    baseStr_dict[(L,germ)] = None
                else:
                    tmpRunningList.append( fullDict[(L,germ)] )
                    baseStr_dict[(L,germ)] = fullDict[(L,germ)]

        super(LsGermsStructure, self).__init__(Ls, germs, prepStrs, effectStrs, baseStr_dict,
                                               fidpair_filters, gstr_filters, gatelabel_aliases)


    def get_all_strings(self):
        """
        Get a list of all the gate strings described by this structure.

        Returns
        -------
        list of GateStrings
        """
        allstrings = []
        prepStrs = self.prepStrs
        effectStrs = self.effectStrs
        
        #build allstrings list on our own
        for L in self.xvals:
            for germ in self.yvals:
                germ_pwr = self.truncFn(germ,L)
                lst = []
                
                if self.gatestring_filters is not None:
                    gs_filter_dict = { gs: True for gs in self.gatestring_filters[(L,germ)] } #fast lookups
                    lst = [ f1 + germ_pwr + f2
                            for f1 in prepStrs for f2 in effectStrs
                            if (f1+germ_pwr+f2) in gs_filter_dict ]
                elif self.fidpair_filters is not None:
                    lst = [ prepStrs[i] + germ_pwr + effectStrs[j]
                            for i,j in self.fidpair_filters[(L,g)] ]
                else:
                    lst = [ f1 + germ_pwr + f2
                            for f1 in prepStrs for f2 in effectStrs ]
                allstrings.extend(lst)
                
        return _lt.remove_duplicates(allstrings)

