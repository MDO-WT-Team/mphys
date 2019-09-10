#!/usr/bin/env python
from __future__ import print_function
from modal_comps import *
import numpy as np

from openmdao.api import Problem, IndepVarComp
from openmdao.api import NonlinearBlockGS, LinearBlockGS
from openmdao.api import ExplicitComponent

class ModalIntegrator(ExplicitComponent):
    def initialize(self):
        self.options.declare('nmodes',default=1)
        self.options.declare('nsteps',default=10)
        self.options.declare('dt',default=1.0)
        self.options.declare('root_name',default='')

    def setup(self):
        nmodes = self.options['nmodes']
        self.add_input('z0',shape=nmodes)
        self.add_input('m',shape=nmodes)
        self.add_input('c',shape=nmodes)
        self.add_input('k',shape=nmodes)
        self.add_input('amp')
        self.add_input('freq')
        self.add_output('z_end',desc = 'final displacement')

        self._setup_step_problem()

        # temporary storage of in memory long term option is async file io
        self.z = np.zeros((self.options['nsteps']+1,nmodes))

    def _setup_step_problem(self):
        """
        OpenMDAO problem solved at each time step
        """
        nmodes    = self.options['nmodes']
        dt        = self.options['dt']
        root_name = self.options['root_name']

        self.problem = Problem()
        model = self.problem.model

        indeps = IndepVarComp()
        indeps.add_output('m',np.zeros(nmodes))
        indeps.add_output('c',np.zeros(nmodes))
        indeps.add_output('k',np.zeros(nmodes))
        indeps.add_output('amp')
        indeps.add_output('freq')
        indeps.add_output('time')

        indeps.add_output('znm1',np.zeros(nmodes))
        indeps.add_output('znm2',np.zeros(nmodes))
        indeps.add_output('znm3',np.zeros(nmodes))
        indeps.add_output('znm4',np.zeros(nmodes))

        model.add_subsystem('indeps',indeps)
        model.add_subsystem('modal_forces',ModalForces(nmodes=nmodes,root_name=root_name))
        model.add_subsystem('modal_solver',ModalStep(nmodes=nmodes,dt=dt))
        model.add_subsystem('modal_disps' ,ModalDisplacements(nmodes=nmodes,root_name=root_name))
        model.add_subsystem('forcer',HarmonicForcer(root_name=root_name))

        model.nonlinear_solver = NonlinearBlockGS()
        model.linear_solver = LinearBlockGS()

        # coupling loop
        model.connect('modal_forces.mf','modal_solver.f')
        model.connect('modal_solver.zn','modal_disps.md')
        model.connect('modal_disps.dx','forcer.dx')
        model.connect('forcer.f','modal_forces.f')

        # modal properties
        model.connect('indeps.m','modal_solver.m')
        model.connect('indeps.c','modal_solver.c')
        model.connect('indeps.k','modal_solver.k')

        # forcer
        model.connect('indeps.amp','forcer.amp')
        model.connect('indeps.freq','forcer.freq')
        model.connect('indeps.time','forcer.time')

        # time backplanes
        model.connect('indeps.znm1','modal_solver.znm1')
        model.connect('indeps.znm2','modal_solver.znm2')
        model.connect('indeps.znm3','modal_solver.znm3')
        model.connect('indeps.znm4','modal_solver.znm4')

        self.problem.setup()

    def compute(self,inputs,outputs):

        # set design variables
        self.problem['indeps.m'] = inputs['m']
        self.problem['indeps.c'] = inputs['c']
        self.problem['indeps.k'] = inputs['k']
        self.problem['indeps.amp'] = inputs['amp']
        self.problem['indeps.freq'] = inputs['freq']

        # start from step 1 to leave initial conditions as 0
        for step in range(1,self.options['nsteps']+1):
            self.problem['indeps.time'] = step*self.options['dt']
            self._setup_step_backplanes(step,inputs)
            self.problem.run_model()
            self._store_step_output(step)

        # compute integrator function of interest
        outputs['z_end'] = self.z[-1,0]

    def _setup_step_backplanes(self,step,inputs):
        for backplane in range(1,5):
            prior_step = step - backplane
            if prior_step > 0:
                self.problem['indeps.znm'+str(backplane)] = self.z[prior_step,:]
            else:
                self.problem['indeps.znm'+str(backplane)] = inputs['z0']

    def _store_step_output(self,step):
        self.z[step,:] = self.problem['modal_solver.zn']

if __name__=='__main__':
    prob = Problem()
    prob.model.add_subsystem('modal_integrator',ModalIntegrator(nmodes=2,nsteps=10,dt=1.0,root_name='sphere_body1'))
    prob.setup(force_alloc_complex=True)
    prob.check_partials(method='cs',compact_print=True)
