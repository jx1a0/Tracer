import numpy as N

from tracer.surface import *
from tracer.quadric import *
from tracer.cone import *
from tracer.cylinder import *
from tracer.flat_surface import *
from tracer.assembly import *
from tracer.optics_callables import *
from tracer.object import *
from tracer.spatial_geometry import *
from tracer.sources import *
from tracer.tracer_engine import *
from tracer.CoIn_rendering.rendering import *

import time

class RTVF():
	'''
	General class for view factor raytraces.
	num_rays - number of rays fired per bundle
	precision - confidence interval threshold on view factor values for each element and for the combination rule between all elements of the scene.
	'''
	def __init__(self, num_rays=10000, precision=0.01):
		self.num_rays = num_rays
		self.precision = precision
		self.A = Assembly() # VF scene assembly

		self.stdev_store = []
				
	def reset_opt(self):
		'''
		Optics reset script to be able to raytrace again the same object without having energy already stored on the surfaces.
		'''
		S = self.A.get_surfaces()
		for i in xrange(len(S)):
			S[i].get_optics_manager().reset()

	
	def test_precision(self):
		'''
		Routine that gathers the results of the VF binning after a full geometry reaytrace and checks the standard deviations of: 
		1. The value of the actual VF_estimator (passes averaged VF) to check each VF matrix element on its independent variation
		2. The combination rule; taking as arbitrary average 0 in the standard deviation formula.
		Afterwards both standard deviation matrices are tested on the maximum self.precision value and the result is inserted in the progress matrix used in the while loop for each geometry. This progress matrix shuts off the raytrace on elements that already hit their precision target in order to speed up teh calculation. A minimum number of iterations is set in order to avoid unlucky breacks at the start of the routine due to statistical bias on low number of passes.
		'''
		old_VF_esperance = self.VF_esperance
		self.VF_esperance = (self.VF_esperance*N.sum(self.p-self.ray_counts)+self.VF*N.sum(self.ray_counts))/N.sum(self.p)
		self.Qsum = self.Qsum + N.vstack(self.p-self.ray_counts)/self.p*(self.VF_esperance-old_VF_esperance)**2.

		rec = N.vstack(self.areas)*self.VF_esperance
		VF_reciprocity = N.abs(rec-rec.T)

		self.stdev_VF = N.sqrt(self.Qsum/(self.p))
		self.stdev_reciprocity = VF_reciprocity/((N.ones(N.shape(self.VF))*N.vstack(self.areas)+N.ones(N.shape(self.VF))*N.hstack(self.areas))/2.)
		#self.stdev_store.append(self.stdev_reciprocity)

		stdev_test = self.stdev_VF<=(self.precision*self.VF_esperance/3.)
		reciprocity_test = self.stdev_reciprocity<=(2.*self.precision)

		self.progress = N.logical_not(N.logical_and(stdev_test, reciprocity_test))


class Two_N_parameters_cavity_RTVF(RTVF):
	'''
	A class for 2N parameters axisymmetrical cavities composed of frusta and a cone.

	apertureRadius - Radius of the aperture of the geometry
	frustaRadii - List of the successive radii of the frusta, starting from the aperture and following the profile of the geometry.
	frustaDepths - List of the depths of the frusta, starting from the aperture and following the profile of the geometry.
	coneDepth - Depth of the cone to close the geometry.
	el_FRUs - A list describing the discretisation of the frusta in the scene. Each frustum [i] is discretised into el_FRUs[i] elements of equal depths.
	el_CON - The number of discretisation elements of equal depths used for the conical part of the receiver.
	'''
	def __init__(self, apertureRadius, frustaRadii, frustaDepths, coneDepth, el_FRUs, el_CON, num_rays=10000, precision=0.01):

		RTVF.__init__(self, num_rays, precision)
		self.apertureRadius = apertureRadius
		self.frustaRadii = frustaRadii
		self.frustaDepths = frustaDepths
		self.coneDepth = coneDepth
		self.el_FRUs = el_FRUs
		self.el_CON = el_CON

		self.t0=time.clock()

		self.VF = N.zeros((1+N.sum(el_FRUs)+el_CON, 1+N.sum(el_FRUs)+el_CON))
		self.VF2 = N.zeros((1+N.sum(el_FRUs)+el_CON, 1+N.sum(el_FRUs)+el_CON))
		self.progress = N.ones(N.shape(self.VF), dtype=N.bool)

		# Standard deviation computation variables.
		self.VF_esperance = N.zeros(N.shape(self.VF))
		self.VF2_esperance = N.zeros(N.shape(self.VF))
		self.Qsum = N.zeros(N.shape(self.VF))
		self.stdev_VF = N.zeros(N.shape(self.VF))
		self.stdev_reciprocity = N.zeros(N.shape(self.VF))

		areas = N.zeros(N.shape(self.VF)[0])
		self.p = N.zeros(N.shape(self.VF)[0])

		if type(el_FRUs)==int:
			el_FRUs = N.asarray([el_FRUs])
			self.el_FRUs = el_FRUs
		if type(el_CON)==int:
			el_CON = N.asarray([el_CON])
			self.el_CON = el_CON

		# Areas calculations: ___________________________________________________________________
		areas[0] = N.pi*apertureRadius**2. # Aperture

		if apertureRadius==frustaRadii[0]: # Cylinder
			areas[1:1+el_FRUs[0]] = N.pi*2.*frustaRadii[0]*N.sqrt((frustaDepths[0]/el_FRUs[0])**2)
		else: # 1st frustum
			L = N.sqrt((frustaDepths[0])**2+(frustaRadii[0]-apertureRadius)**2)/el_FRUs[0]
			radii = N.hstack([apertureRadius, apertureRadius+(N.arange(el_FRUs[0])+1)*(frustaRadii[0]-apertureRadius)/el_FRUs[0]])
			areas[1:1+el_FRUs[0]] = N.pi*(radii[:-1]+radii[1:])*L

		for k in xrange(1,len(el_FRUs)): # next frusta
			if self.frustaRadii[k-1]==self.frustaRadii[k]:
				areas[1+N.sum(el_FRUs[:k+1])-el_FRUs[k]:1+N.sum(el_FRUs[:k+1])] = 2.*N.pi*frustaRadii[k]*N.sqrt((frustaDepths[k]/el_FRUs[k])**2)
			else:
				L = N.sqrt(frustaDepths[k]**2+(frustaRadii[k]-frustaRadii[k-1])**2)/el_FRUs[k]
				radii = N.hstack([frustaRadii[k-1],frustaRadii[k-1]+(N.arange(el_FRUs[k])+1)*(frustaRadii[k]-frustaRadii[k-1])/el_FRUs[k]])
				areas[1+N.sum(el_FRUs[:k+1])-el_FRUs[k]:1+N.sum(el_FRUs[:k+1])] = N.pi*(radii[:-1]+radii[1:])*L

		radii = N.hstack([frustaRadii[-1],frustaRadii[-1]+(N.arange(el_CON)+1)*(-frustaRadii[-1])/el_CON])
		areas[1+N.sum(el_FRUs):1+N.sum(el_FRUs)+el_CON] = N.pi*(radii[:-1]+radii[1:])*N.sqrt(coneDepth**2+frustaRadii[-1]**2)/el_CON # Cone

		self.areas = areas

		#_______________________________________________________________________________________
		self.ray_counts = N.ones(len(areas))*int(self.num_rays/len(areas))


		# Build the geometry:___________________________________________________________________
		max_depth = N.sum(frustaDepths)

		AP = AssembledObject(surfs=[Surface(RoundPlateGM(Re=apertureRadius), LambertianReceiver(absorptivity=1.))], transform = None)

		FRU = []
		# 1st frustum:
		if apertureRadius==frustaRadii[0]: # Cylinder
			frustum = AssembledObject(surfs=[Surface(FiniteCylinder(diameter=frustaRadii[0]*2., height=frustaDepths[0]), LambertianReceiver(absorptivity=1.))], transform=translate(z=frustaDepths[0]/2.))
		else: # frustum
			frustum = AssembledObject(surfs=[Surface(ConicalFrustum(z1=0., r1=apertureRadius, z2=frustaDepths[0], r2=frustaRadii[0]), LambertianReceiver(absorptivity=1.))], transform=None)
		FRU.append(frustum)
		# next frusta:
		for i in xrange(1,len(frustaRadii)):
			if self.frustaRadii[i-1]==self.frustaRadii[i]:
				frustum = AssembledObject(surfs=[Surface(FiniteCylinder(diameter=self.frustaRadii[i]*2., height=self.frustaDepths[i]), LambertianReceiver(absorptivity=1.))], transform=translate(z=N.sum(self.frustaDepths[:i])+self.frustaDepths[i]/2.))
			elif self.frustaDepths[i] < 0.:
				frustum = AssembledObject(surfs=[Surface(ConicalFrustum(z1=0., r1=self.frustaRadii[i-1], z2=-self.frustaDepths[i], r2=self.frustaRadii[i]), LambertianReceiver(absorptivity=1.))], transform=N.dot(translate(z=N.sum(self.frustaDepths[:i])),rotx(N.pi)))
			else:
				frustum = AssembledObject(surfs=[Surface(ConicalFrustum(z1=0., r1=self.frustaRadii[i-1], z2=self.frustaDepths[i], r2=self.frustaRadii[i]), LambertianReceiver(absorptivity=1.))], transform=translate(z=N.sum(self.frustaDepths[:i])))
			FRU.append(frustum)

		# Cone section:
		if coneDepth>0.: # == cone depth > 0: Outgoing cone
			trc = N.dot(rotx(N.pi), translate(z=-(max_depth+coneDepth))) # Cone frame transformation
			CON = AssembledObject(surfs=[Surface(FiniteCone(r=frustaRadii[-1], h=coneDepth), LambertianReceiver(absorptivity=1.))], transform=trc)
			rays_cone=True
		elif coneDepth == 0.: # Round flat plates
			CON = AssembledObject(surfs=[Surface(RoundPlateGM(Re=frustaRadii[-1]), LambertianReceiver(absorptivity=1.))], transform=translate(z=max_depth))
		else: # coneDepth < 0 Inward cone
			CON = AssembledObject(surfs=[Surface(FiniteCone(r=frustaRadii[-1], h=-coneDepth), LambertianReceiver(absorptivity=1.))], transform=translate(z=max_depth+coneDepth))
			rays_cone=False

		self.A.add_object(AP)
		for i in xrange(len(FRU)):
			self.A.add_object(FRU[i])
		self.A.add_object(CON)

		self.AP = AP
		self.CON = CON
		self.FRU = FRU

		apertureRadius = self.apertureRadius
		frustaRadii = self.frustaRadii
		frustaDepths = self.frustaDepths
		coneDepth = self.coneDepth
		el_FRUs = self.el_FRUs
		el_CON = self.el_CON

		vf_tracer = TracerEngine(self.A)
		itmax = 1 # stop iteration after this many ray bundles were generated (i.e. after the original rays intersected some surface this many times).
		minener = 1e-15 # minimum energy threshold

		while (self.progress==True).any():

			tp = time.clock()

			if self.ray_counts[0] != 0.:

				SA = solar_disk_bundle(self.ray_counts[0], center=N.vstack([0,0,0]), direction=N.array([0,0,1]), radius=apertureRadius, ang_range=N.pi/2., flux=1./(N.pi*apertureRadius**2))

				vf_tracer.ray_tracer(SA, itmax, minener, tree = True)
				#view = Renderer(vf_tracer)
				#view.show_geom()
				#vf_tracer.minener=1e-5
				#view.show_rays()
				self.alloc_VF(0)


			for elf in xrange(int(el_FRUs[0])):
				if self.ray_counts[elf+1] != 0.:

					if apertureRadius==frustaRadii[0]:
						S = vf_cylinder_bundle(self.ray_counts[elf+1], rc=frustaRadii[0], lc=frustaDepths[0]/el_FRUs[0], center=N.vstack([0,0,elf*frustaDepths[0]/el_FRUs[0]]), direction=N.array([0,0,1]), rays_in=True)
					else:
						S = vf_frustum_bundle(self.ray_counts[elf+1], r0=apertureRadius+elf*(frustaRadii[0]-apertureRadius)/el_FRUs[0], r1=apertureRadius+(elf+1)*(frustaRadii[0]-apertureRadius)/el_FRUs[0], depth=frustaDepths[0]/el_FRUs[0], center=N.vstack([0,0,elf*frustaDepths[0]/el_FRUs[0]]), direction=N.array([0,0,1]), rays_in=True)

					vf_tracer.ray_tracer(S, itmax, minener, tree = True)
					#view = Renderer(vf_tracer)
					#vf_tracer.minener=minener
					#view.show_rays()
					self.alloc_VF(elf+1)


			for n in xrange(1,len(el_FRUs)):
				for elf in xrange(int(el_FRUs[n])):
					if self.ray_counts[1+N.sum(el_FRUs[:n+1])-el_FRUs[n]+elf] != 0.:
	
						if frustaDepths[n] < 0.:
							rays_in_frun = False
						else:
							rays_in_frun = True

						if frustaRadii[n-1]==frustaRadii[n]:
							S = vf_cylinder_bundle(self.ray_counts[1+N.sum(el_FRUs[:n+1])-el_FRUs[n]+elf], rc=frustaRadii[n], lc=frustaDepths[n]/el_FRUs[n], center=N.vstack([0,0,N.sum(frustaDepths[:n])+elf*frustaDepths[n]/el_FRUs[n]]), direction=N.array([0,0,1]), rays_in=rays_in_frun)
						else:
		
							S = vf_frustum_bundle(self.ray_counts[1+N.sum(el_FRUs[:n+1])-el_FRUs[n]+elf], r0=frustaRadii[n-1]+elf*(frustaRadii[n]-frustaRadii[n-1])/el_FRUs[n], r1=frustaRadii[n-1]+(elf+1)*(frustaRadii[n]-frustaRadii[n-1])/el_FRUs[n], depth=frustaDepths[n]/el_FRUs[n], center=N.vstack([0,0,N.sum(frustaDepths[:n])+elf*frustaDepths[n]/el_FRUs[n]]), direction=N.array([0,0,1]), rays_in=rays_in_frun)

						vf_tracer.ray_tracer(S, itmax, minener, tree = True)
						#view = Renderer(vf_tracer)
						#vf_tracer.minener=minener
						#view.show_rays()
						self.alloc_VF(1+N.sum(el_FRUs[:n+1])-el_FRUs[n]+elf)

			for elc in xrange(int(el_CON)):
				if self.ray_counts[N.sum(el_FRUs)+elc+1] != 0.:

					if coneDepth==0.:
						S = solar_disk_bundle(self.ray_counts[N.sum(el_FRUs)+elc+1], center=N.vstack([0,0,N.sum(frustaDepths)]), direction=N.array([0,0,-1]), radius=frustaRadii[-1]+elc*(-frustaRadii[-1])/el_CON, ang_range=N.pi/2., flux=1./(N.pi*frustaRadii[-1]**2), radius_in=frustaRadii[-1]+(elc+1)*(-frustaRadii[-1])/el_CON)

					else:
						S = vf_frustum_bundle(self.ray_counts[N.sum(el_FRUs)+elc+1], r0=frustaRadii[-1]+elc*(-frustaRadii[-1])/el_CON, r1=frustaRadii[-1]+(elc+1)*(-frustaRadii[-1])/el_CON, depth=coneDepth/el_CON, center=N.vstack([0,0,N.sum(frustaDepths)+coneDepth*elc/el_CON]), direction=N.array([0,0,1]), rays_in=rays_cone)

					vf_tracer.ray_tracer(S, itmax, minener, tree = True)
					self.alloc_VF(N.sum(el_FRUs)+elc+1)


			self.p += self.ray_counts
			self.test_precision()
			print '		Progress:', N.sum(self.progress),'/', N.shape(self.progress)[0]**2.,'; Pass duration:', time.clock()-tp, 's'
			'''
			if self.p[0]>5e6:
				self.stdev_store = N.array(self.stdev_store)
				for h in xrange(N.shape(self.stdev_store)[1]):
					for v in xrange(N.shape(self.stdev_store)[2]):
						plt.plot(N.arange(0, self.p[0], self.ray_counts[0]), self.stdev_store[:,h,v], label= str(h)+str(v))
				plt.legend()
				plt.show()
		self.stdev_store = N.array(self.stdev_store)
		for h in xrange(N.shape(self.stdev_store)[1]):
			for v in xrange(N.shape(self.stdev_store)[2]):
				plt.plot(N.arange(0, self.p[0], self.ray_counts[0]), self.stdev_store[:,h,v], label= str(h)+str(v))
		plt.legend()
		plt.show()
			'''
		t1=time.clock()-self.t0
		print '	VF calculation time:',t1,'s'

	def alloc_VF(self, n):
		'''
		get hits in the scene and bin them in VF matrix.
		'''
		apertureRadius = self.apertureRadius
		frustaRadii = self.frustaRadii
		frustaDepths = self.frustaDepths
		coneDepth = self.coneDepth
		el_FRUs = self.el_FRUs
		el_CON = self.el_CON

		# Gather hits and absorbed radiative power
		Aperture_abs, Aperture_hits = self.AP.get_surfaces()[0].get_optics_manager().get_all_hits()
		Frustum_abs = []
		Frustum_hits = []
		for i in xrange(len(el_FRUs)):
			Fru_abs, Fru_hits = self.FRU[i].get_surfaces()[0].get_optics_manager().get_all_hits()
			Frustum_abs.append(N.asarray(Fru_abs))
			Frustum_hits.append(N.asarray(Fru_hits))
		Cone_abs, Cone_hits = self.CON.get_surfaces()[0].get_optics_manager().get_all_hits()

		# VF allocation to a nxn VF matrix. Convention is to go from the aperture to the back of the shape following the axi-symmetric profile line. First loop is for gemoetrical shapes and second one for the discretisation of each shape.
		for j in xrange(len(el_FRUs)+2):

			if j == 0:
				self.VF[n,j] = N.sum(Aperture_abs)


			elif j <= len(el_FRUs):
				for i in xrange(int(el_FRUs[j-1])):
					frustum_el_base = N.sum(frustaDepths[:j])-frustaDepths[j-1]+i*frustaDepths[j-1]/el_FRUs[j-1]
					frustum_el_top = N.sum(frustaDepths[:j])-frustaDepths[j-1]+(i+1)*frustaDepths[j-1]/el_FRUs[j-1]
					if frustaDepths[j-1]<0.:
						frustum_el_base, frustum_el_top = frustum_el_top, frustum_el_base
					in_frustum_el = N.logical_and(Frustum_hits[j-1][2]>=frustum_el_base, Frustum_hits[j-1][2]<frustum_el_top)
					self.VF[n,i+1+N.sum(el_FRUs[:j])-el_FRUs[j-1]] = N.sum(Frustum_abs[j-1][in_frustum_el])

			else:
				for i in xrange(int(el_CON)):

					r1 = frustaRadii[-1]-i*frustaRadii[-1]/el_CON
					r2 = frustaRadii[-1]-(i+1)*frustaRadii[-1]/el_CON

					cone_hits_radii = N.sqrt(Cone_hits[0]**2+Cone_hits[1]**2)
					in_cone_el = N.logical_and(cone_hits_radii<r1, cone_hits_radii>=r2)
		
					self.VF[n,i+1+N.sum(el_FRUs)] = N.sum(Cone_abs[in_cone_el])

		self.reset_opt()

class Four_parameters_cavity_RTVF(Two_N_parameters_cavity_RTVF):
	'''
	Wrapper around the Two_N_parameters_cavity_RTVF class to a 4 parameters cavity.
	ref: "Open cavity receiver geometry influence on radiative losses" (DOI:10.13140/2.1.3845.5048)
	'''
	def __init__(self, apertureRadius, apertureDepth, coneRadius, coneDepth, el_FRU, el_CON, num_rays, precision):
		Two_N_parameters_cavity_RTVF.__init__(self, apertureRadius, [coneRadius], [apertureDepth], coneDepth, el_FRU, el_CON, num_rays, precision)

