""" 
Variables for working with the a gatest containing Idle, Z(pi/2) and rot(X=pi/2, Y=sqrt(3)/2) gates.
"""

import gatestringconstruction as _strc
import gatesetconstruction as _setc


gs_target = _setc.build_gateset([2],[('Q0',)], ['Gz','Gn'], 
                                [ "Z(pi/2,Q0)", "N(pi/2, sqrt(3)/2, 0, -0.5, Q0)"],
                                rhoExpressions=["0"], EExpressions=["1"], 
                                spamLabelDict={'plus': (0,0), 'minus': (0,-1) } )

prepFiducials = _strc.gatestring_list([(),
                                       ('Gn',),
                                       ('Gn','Gn'),
                                       ('Gn','Gz','Gn'),
                                       ('Gn','Gn','Gn',),
                                       ('Gn','Gz','Gn','Gn','Gn')]) # for 1Q MUB
                                               
measFiducials = _strc.gatestring_list([(),
                                       ('Gn',),
                                       ('Gn','Gn'),
                                       ('Gn','Gz','Gn'),
                                       ('Gn','Gn','Gn',),
                                       ('Gn','Gn','Gn','Gz','Gn')]) # for 1Q MUB

germs = _strc.gatestring_list([ ('Gz',),
                                ('Gn',),
                                ('Gn','Gn','Gz','Gn','Gz'),
                                ('Gn','Gz','Gn','Gz','Gz'),
                                ('Gn','Gz','Gn','Gn','Gz','Gz'),
                                ('Gn','Gn','Gz','Gn','Gz','Gz'),
                                ('Gn','Gn','Gn','Gz','Gz','Gz') ])
