from headers import *

##################################################################################
##################################################################################

class ThumbStack(object):

#   def __init__(self, U, Catalog, pathMap="", pathMask="", pathHit="", name="test", nameLong=None, save=False, nProc=1):
   def __init__(self, U, Catalog, cmbMap, cmbMask, cmbHit=None, name="test", nameLong=None, save=False, nProc=1, filterTypes='diskring', doStackedMap=False):
      
      self.nProc = nProc
      self.U = U
      self.Catalog = Catalog
      self.name = name
      if nameLong is None:
         self.nameLong = self.name
      else:
         self.nameLong = nameLong
      self.cmbMap = cmbMap
      self.cmbMask = cmbMask
      self.cmbHit = cmbHit

      # aperture photometry filters to implement
      if filterTypes=='diskring':
         self.filterTypes = np.array(['diskring']) 
      elif filterTypes=='disk':
         self.filterTypes = np.array(['disk'])
      elif filterTypes=='ring':
         self.filterTypes = np.array(['ring'])
      elif filterTypes=='all':
         self.filterTypes = np.array(['diskring', 'disk', 'ring'])

      # estimators (ksz, tsz) and weightings (uniform, hit, var, ...)
      # for stacked profiles, bootstrap cov and v-shuffle cov
      if self.cmbHit is not None:
         self.Est = ['tsz_uniformweight', 'tsz_hitweight', 'tsz_varweight', 'ksz_uniformweight', 'ksz_hitweight', 'ksz_varweight', 'ksz_massvarweight']
         self.EstBootstrap = ['tsz_varweight', 'ksz_varweight']
         self.EstVShuffle = ['ksz_varweight']
      else:
         self.Est = ['tsz_uniformweight', 'ksz_uniformweight', 'ksz_massvarweight']
         self.EstBootstrap = ['tsz_uniformweight', 'ksz_uniformweight']
         self.EstVShuffle = ['ksz_uniformweight']

      # resolution of the cutout maps to be extracted
      self.resCutoutArcmin = 0.25   # [arcmin]
      # projection of the cutout maps
      self.projCutout = 'cea'

      # number of samples for bootstraps, shuffles
      self.nSamples = 100
      
      # Output path
      self.pathOut = "./output/thumbstack/"+self.name
      if not os.path.exists(self.pathOut):
         os.makedirs(self.pathOut)

      # Figures path
      self.pathFig = "./figures/thumbstack/"+self.name
      if not os.path.exists(self.pathFig):
         os.makedirs(self.pathFig)
      # test figures path
      self.pathTestFig = self.pathFig+"/tests"
      if not os.path.exists(self.pathTestFig):
         os.makedirs(self.pathTestFig)

      print "- Thumbstack: "+str(self.name)
      
      self.loadAPRadii()
      
      if save:
         self.saveOverlapFlag(nProc=self.nProc)
      self.loadOverlapFlag()
      
      if save:
         self.saveFiltering(nProc=self.nProc)
      self.loadFiltering()
      
      self.measureAllVarFromHitCount(plot=save)

      if save:
         self.saveAllStackedProfiles()
      self.loadAllStackedProfiles()

      if save:
         self.plotAllStackedProfiles()
         self.plotAllCov()
         self.computeAllSnr()

      if doStackedMap:
         # save all stacked maps
         #self.saveAllStackedMaps()
         # save only the stacked maps for
         # the best tsz and ksz estimators,
         # and for the diskring weighting
         self.saveAllStackedMaps(filterTypes=['diskring'], Est=['tsz_varweight', 'ksz_varweight'])



   ##################################################################################
   ##################################################################################
   
   def loadAPRadii(self):
      # radii to use for AP filter: comoving Mpc/h
      self.nRAp = 9 #30 #9  #4
      
      # Aperture radii in Mpc/h
      self.rApMinMpch = 1.
      self.rApMaxMpch = 5
      self.RApMpch = np.linspace(self.rApMinMpch, self.rApMaxMpch, self.nRAp)
      
      # Aperture radii in arcmin
      self.rApMinArcmin = 1.  #0.1   #1.  # 1.
      self.rApMaxArcmin = 6.  #6.  #6.  # 4.
      self.RApArcmin = np.linspace(self.rApMinArcmin, self.rApMaxArcmin, self.nRAp)


   def cutoutGeometry(self):
      '''Create enmap for the cutouts to be extracted.
      Returns a null enmap object with the right shape and wcs.
      '''
      
      # choose postage stamp size to fit the largest ring
      dArcmin = np.ceil(2. * self.rApMaxArcmin * np.sqrt(2.))
      #
      nx = np.floor((dArcmin / self.resCutoutArcmin - 1.) / 2.) + 1.
      dxDeg = (2. * nx + 1.) * self.resCutoutArcmin / 60.
      ny = np.floor((dArcmin / self.resCutoutArcmin - 1.) / 2.) + 1.
      dyDeg = (2. * ny + 1.) * self.resCutoutArcmin / 60.

      # define geometry of small square maps to be extracted
      shape, wcs = enmap.geometry(np.array([[-0.5*dxDeg,-0.5*dyDeg],[0.5*dxDeg,0.5*dyDeg]])*utils.degree, res=self.resCutoutArcmin*utils.arcmin, proj=self.projCutout)
      cutoutMap = enmap.zeros(shape, wcs)
      return cutoutMap

   ##################################################################################
   

   def sky2map(self, ra, dec, map):
      '''Gives the map value at coordinates (ra, dec).
      ra, dec in degrees.
      Uses nearest neighbor, no interpolation.
      Will return 0 if the coordinates requested are outside the map
      '''
      # interpolate the map to the given sky coordinates
      sourcecoord = np.array([dec, ra]) * utils.degree   # convert from degrees to radians
      # use nearest neighbor interpolation
      return map.at(sourcecoord, prefilter=False, mask_nan=False, order=0)
   
   
   
   #def saveOverlapFlag(self, thresh=1.e-5, nProc=1):
   def saveOverlapFlag(self, thresh=0.95, nProc=1):
      '''1 for objects that overlap with the hit map,
      0 for objects that don't.
      '''
      print "Create overlap flag"
      # find if a given object overlaps with the CMB hit map
      def foverlap(iObj):
         '''Returns 1. if the object overlaps with the hit map and 0. otherwise.
         '''
         if iObj%100000==0:
            print "-", iObj
         ra = self.Catalog.RA[iObj]
         dec = self.Catalog.DEC[iObj]
         #hit = self.sky2map(ra, dec, self.cmbHit)
         hit = self.sky2map(ra, dec, self.cmbMask)
         return np.float(hit>thresh)
      
#      overlapFlag = np.array(map(foverlap, range(self.Catalog.nObj)))
      tStart = time()
      with sharedmem.MapReduce(np=nProc) as pool:
         overlapFlag = np.array(pool.map(foverlap, range(self.Catalog.nObj)))
      tStop = time()
      print "took", (tStop-tStart)/60., "min"
      print "Out of", self.Catalog.nObj, "objects,", np.sum(overlapFlag), "overlap, ie a fraction", np.sum(overlapFlag)/self.Catalog.nObj
      np.savetxt(self.pathOut+"/overlap_flag.txt", overlapFlag)
   
   
   def loadOverlapFlag(self):
      self.overlapFlag = np.genfromtxt(self.pathOut+"/overlap_flag.txt")
   
   
   ##################################################################################
   
   def examineCmbMaps(self):
   
      # mask, before re-thresholding
      x = self.cmbMask.copy()
      path = self.pathFig+"/hist_cmbmask_prerethresh.pdf"
      myHistogram(x, nBins=71, lim=(np.min(x), np.max(x)), path=path, nameLatex=r'CMB mask value', semilogy=True)

      # rethreshold the mask
      mask = (self.cmbMask>0.5)[0]

      # mask, after re-thresholding
      x = 1. * mask.copy()
      path = self.pathFig+"/hist_cmbmask_postrethresh.pdf"
      myHistogram(x, nBins=71, lim=(np.min(x), np.max(x)), path=path, nameLatex=r'CMB mask value', semilogy=True)

      # masked map histogram
      x = self.cmbMap[mask]
      path = self.pathFig+"/hist_cmbmap.pdf"
      myHistogram(x, nBins=71, lim=(-10.*np.std(x), 10.*np.std(x)), path=path, nameLatex=r'CMB map value', semilogy=True, doGauss=True, S2Theory=[110.**2])

      # masked hit count histogram
      x = self.cmbHit[mask]
      path = self.pathFig+"/hist_cmbhit.pdf"
      myHistogram(x, nBins=71, lim=(np.min(x), np.max(x)), path=path, nameLatex=r'CMB hit count', semilogy=True)
   
   
   ##################################################################################
   

   def extractStamp(self, ra, dec, test=False):
      """Extracts a small CEA or CAR map around the given position, with the given angular size and resolution.
      ra, dec in degrees.
      Does it for the map, the mask and the hit count.
      """

      stampMap = self.cutoutGeometry()
      stampMask = stampMap.copy()
      stampHit = stampMap.copy()

      # coordinates of the square map (between -1 and 1 deg)
      # output map position [{dec,ra},ny,nx]
      opos = stampMap.posmap()

      # coordinate of the center of the square map we want to extract
      # ra, dec in this order
      sourcecoord = np.array([ra, dec])*utils.degree  # convert from degrees to radians

      # corresponding true coordinates on the big healpy map
      ipos = rotfuncs.recenter(opos[::-1], [0,0,sourcecoord[0],sourcecoord[1]])[::-1]

      # extract the small square map by interpolating the big map
      # these are now numpy arrays: the wcs info is gone

#      # Here, I use nearest neighbor interpolation (order=0)
#      stampMap[:,:] = self.cmbMap.at(ipos, prefilter=False, mask_nan=False, order=0)
#      stampMask[:,:] = self.cmbMask.at(ipos, prefilter=False, mask_nan=False, order=0)
#      stampHit[:,:] = self.cmbHit.at(ipos, prefilter=False, mask_nan=False, order=0)
      
      # Here, I use bilinear interpolation
      stampMap[:,:] = self.cmbMap.at(ipos, prefilter=True, mask_nan=False, order=1)
      stampMask[:,:] = self.cmbMask.at(ipos, prefilter=True, mask_nan=False, order=1)
      if self.cmbHit is not None:
         stampHit[:,:] = self.cmbHit.at(ipos, prefilter=True, mask_nan=False, order=1)

#      # Here, I use bicubic spline interpolation
#      stampMap[:,:] = self.cmbMap.at(ipos, prefilter=True, mask_nan=False, order=3)
#      stampMask[:,:] = self.cmbMask.at(ipos, prefilter=True, mask_nan=False, order=3)
#      stampHit[:,:] = self.cmbHit.at(ipos, prefilter=True, mask_nan=False, order=3)


      # re-threshold the mask map, to keep 0 and 1 only
      stampMask[:,:] = 1.*(stampMask[:,:]>0.5)

      if test:
         print "Extracted cutouts around ra=", ra, "dec=", dec
         
         print "Map:"
         print "- min, mean, max =", np.min(stampMap), np.mean(stampMap), np.max(stampMap)
         print "- plot"
         plots=enplot.plot(stampMap, grid=True)
         enplot.write(self.pathTestFig+"/stampmap_ra"+np.str(np.round(ra, 2))+"_dec"+np.str(np.round(dec, 2)), plots)

         print "Mask:"
         print "- min, mean, max =", np.min(stampMask), np.mean(stampMask), np.max(stampMask)
         print "- plot"
         plots=enplot.plot(stampMask, grid=True)
         enplot.write(self.pathTestFig+"/stampmask_ra"+np.str(np.round(ra, 2))+"_dec"+np.str(np.round(dec, 2)), plots)

         print "Hit count:"
         print "- min, mean, max =", np.min(stampHit), np.mean(stampHit), np.max(stampHit)
         print "- plot the hit"
         plots=enplot.plot(stampHit, grid=True)
         enplot.write(self.pathTestFig+"/stamphit_ra"+np.str(np.round(ra, 2))+"_dec"+np.str(np.round(dec, 2)), plots)

      return opos, stampMap, stampMask, stampHit



   ##################################################################################


   def aperturePhotometryFilter(self, opos, stampMap, stampMask, stampHit, r0, r1, filterType='diskring',  test=False):
      """Apply an AP filter (disk minus ring) to a stamp map:
      AP = int d^2theta * Filter * map.
      Unit is [map unit * sr]
      The filter function is dimensionless:
      Filter = 1 in the disk, - (disk area)/(ring area) in the ring, 0 outside.
      Hence:
      int d^2theta * Filter = 0.
      r0 and r1 are the radius of the disk and ring in radians.
      stampMask should have values 0 and 1 only.
      Output:
      filtMap: [map unit * sr]
      filtMask: [mask unit * sr]
      filtHitNoiseStdDev: [1/sqrt(hit unit) * sr], ie [std dev * sr] if [hit map] = inverse var
      diskArea: [sr]
      """
      # coordinates of the square map in radians
      # zero is at the center of the map
      # output map position [{dec,ra},ny,nx]
      dec = opos[0,:,:]
      ra = opos[1,:,:]
      radius = np.sqrt(ra**2 + dec**2)
      # exact angular area of a pixel [sr] (same for all pixels in CEA, not CAR)
      pixArea = ra.area() / len(ra.flatten())
      
      # detect point sources within the filter:
      # gives 0 in the absence of point sources/edges; gives >=1 in the presence of point sources/edges
      filtMask = np.sum((radius<=r1) * (1-stampMask))   # [dimensionless]

      # disk filter [dimensionless]
      inDisk = 1.*(radius<=r0)
      # exact angular area of disk [sr]
      diskArea = np.sum(inDisk) * pixArea
      # ring filter [dimensionless]
      inRing = 1.*(radius>r0)*(radius<=r1)

      if filterType=='diskring':
         # normalize the ring so that the disk-ring filter integrates exactly to zero
         inRing *= np.sum(inDisk) / np.sum(inRing)
         # disk minus ring filter [dimensionless]
         filterW = inDisk - inRing
         if np.isnan(np.sum(filterW)):
            print "filterW sums to nan", r0, r1, np.sum(radius), np.sum(1.*(radius>r0)), np.sum(1.*(radius>r0)*(radius<=r1))
      elif filterType=='disk':
         # disk filter [dimensionless]
         inDisk = 1.*(radius<=r0)
         filterW = inDisk
      elif filterType=='ring':
         filterW = inRing
      elif filterType=='meanring':
         filterW = inRing / np.sum(pixArea * inRing)

      # apply the filter: int_disk d^2theta map -  disk_area / ring_area * int_ring d^2theta map
      filtMap = np.sum(pixArea * filterW * stampMap)   # [map unit * sr]
      # quantify noise std dev in the filter
      if self.cmbHit is not None:
         filtHitNoiseStdDev = np.sqrt(np.sum((pixArea * filterW)**2 / (1.e-16 + stampHit))) # to get the std devs [sr / sqrt(hit unit)]
      else:
         filtHitNoiseStdDev = 0.
      

      #print "filtHitNoiseStdDev = ", filtHitNoiseStdDev
      if np.isnan(filtHitNoiseStdDev):
         print "filtHitNoiseStdDev is nan"

      if test:
         print "AP filter with disk radius =", r0 * (180.*60./np.pi), "arcmin"
         # count nb of pixels where filter is strictly positive
         nbPix = len(np.where(filterW>0.)[0])
         print "- nb of pixels in the cutout: "+str(filterW.shape[0] * filterW.shape[1])
         print "= nb of pixels where filter=0: "+str(len(np.where(filterW==0.)[0]))
         print "+ nb of pixels where filter>0: "+str(len(np.where(filterW>0.)[0]))
         print "+ nb of pixels where filter<0: "+str(len(np.where(filterW<0.)[0]))
         print "- disk area: "+str(diskArea)+" sr, ie "+str(diskArea * (180.*60./np.pi)**2)+"arcmin^2"
         print "  (from r0, expect "+str(np.pi*r0**2)+" sr, ie "+str(np.pi*r0**2 * (180.*60./np.pi)**2)+"arcmin^2)"
         print "- disk-ring filter sums over pixels to "+str(np.sum(filterW))
         print "  (should be 0; compared to "+str(len(filterW.flatten()))+")"
         print "- filter on unit disk: "+str(np.sum(pixArea * filterW * inDisk))
         print "  (should be disk area in sr: "+str(diskArea)+")"
         print "- filter on map: "+str(filtMap)
         print "- filter on mask: "+str(filtMask)
         print "- filter on inverse hit: "+str(filtHitNoiseStdDev)
         print "- plot the filter"
         filterMap = stampMap.copy()
         filterMap[:,:] = filterW.copy()
         plots=enplot.plot(filterMap,grid=True)
         enplot.write(self.pathTestFig+"/stampfilter_r0"+floatExpForm(r0)+"_r1"+floatExpForm(r1), plots)

      return filtMap, filtMask, filtHitNoiseStdDev, diskArea




   ##################################################################################

   def analyzeObject(self, iObj, test=False):
      '''Analysis to be done for each object: extract cutout map once,
      then apply all aperture photometry filters requested on it.
      Returns:
      filtMap: [map unit * sr]
      filtMask: [mask unit * sr]
      filtHitNoiseStdDev: [1/sqrt(hit unit) * sr], ie [std dev * sr] if [hit map] = inverse var
      diskArea: [sr]
      '''
      
      if iObj%10000==0:
         print "- analyze object", iObj
      
      
      # create arrays of filter values for the given object
      filtMap = {}
      filtMask = {}
      filtHitNoiseStdDev = {} 
      filtArea = {}
      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]
         # create arrays of filter values for the given object
         filtMap[filterType] = np.zeros(self.nRAp)
         filtMask[filterType] = np.zeros(self.nRAp)
         filtHitNoiseStdDev[filterType] = np.zeros(self.nRAp)
         filtArea[filterType] = np.zeros(self.nRAp)
      
      # only do the analysis if the object overlaps with the CMB map
      if self.overlapFlag[iObj]:
         # Object coordinates
         ra = self.Catalog.RA[iObj]   # in deg
         dec = self.Catalog.DEC[iObj] # in deg
         z = self.Catalog.Z[iObj]
         # choose postage stamp size to fit the largest ring
         dArcmin = np.ceil(2. * self.rApMaxArcmin * np.sqrt(2.))
         dDeg = dArcmin / 60.
         # extract postage stamp around it
         opos, stampMap, stampMask, stampHit = self.extractStamp(ra, dec, test=test)
         
         for iFilterType in range(len(self.filterTypes)):
            filterType = self.filterTypes[iFilterType]

            # loop over the radii for the AP filter
            for iRAp in range(self.nRAp):
               ## disk radius in comoving Mpc/h
               #rApMpch = self.RApMpch[iRAp]
               ## convert to radians at the given redshift
               #r0 = rApMpch / self.U.bg.comoving_transverse_distance(z) # rad

               # Disk radius in rad
               r0 = self.RApArcmin[iRAp] / 60. * np.pi/180.
               # choose an equal area AP filter
               r1 = r0 * np.sqrt(2.)
               
               # perform the filtering
               filtMap[filterType][iRAp], filtMask[filterType][iRAp], filtHitNoiseStdDev[filterType][iRAp], filtArea[filterType][iRAp] = self.aperturePhotometryFilter(opos, stampMap, stampMask, stampHit, r0, r1, filterType=filterType, test=test)

      if test:
         print " plot the measured profile"
         fig=plt.figure(0)
         ax=fig.add_subplot(111)
         #
         for iFilterType in range(len(self.filterTypes)):
            filterType = self.filterTypes[iFilterType]
            ax.plot(self.RApArcmin, filtMap[filterType])
         #
         plt.show()

      return filtMap, filtMask, filtHitNoiseStdDev, filtArea



   def saveFiltering(self, nProc=1):
      
      print("Evaluate all filters on all objects")
      # loop over all objects in catalog
#      result = np.array(map(self.analyzeObject, range(self.Catalog.nObj)))
      tStart = time()
      with sharedmem.MapReduce(np=nProc) as pool:
         f = lambda iObj: self.analyzeObject(iObj, test=False)
         result = np.array(pool.map(f, range(self.Catalog.nObj)))
      tStop = time()
      print "took", (tStop-tStart)/60., "min"


      # unpack and save to file
      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]

         filtMap = np.array([result[iObj,0][filterType][:] for iObj in range(self.Catalog.nObj)])
         filtMask = np.array([result[iObj,1][filterType][:] for iObj in range(self.Catalog.nObj)])
         filtHitNoiseStdDev = np.array([result[iObj,2][filterType][:] for iObj in range(self.Catalog.nObj)])
         filtArea = np.array([result[iObj,3][filterType][:] for iObj in range(self.Catalog.nObj)])
         
         np.savetxt(self.pathOut+"/"+filterType+"_filtmap.txt", filtMap)
         np.savetxt(self.pathOut+"/"+filterType+"_filtmask.txt", filtMask)
         np.savetxt(self.pathOut+"/"+filterType+"_filtnoisestddev.txt", filtHitNoiseStdDev)
         np.savetxt(self.pathOut+"/"+filterType+"_filtarea.txt", filtArea)


   def loadFiltering(self):
      self.filtMap = {}
      self.filtMask = {}
      self.filtHitNoiseStdDev = {}
      self.filtArea = {}

      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]
         self.filtMap[filterType] = np.genfromtxt(self.pathOut+"/"+filterType+"_filtmap.txt")
         self.filtMask[filterType] = np.genfromtxt(self.pathOut+"/"+filterType+"_filtmask.txt")
         self.filtHitNoiseStdDev[filterType] = np.genfromtxt(self.pathOut+"/"+filterType+"_filtnoisestddev.txt")
         self.filtArea[filterType] = np.genfromtxt(self.pathOut+"/"+filterType+"_filtarea.txt")


   ##################################################################################


   def catalogMask(self, overlap=True, psMask=True, mVir=[1.e6, 1.e17], z=[0., 100.], extraSelection=1., filterType=None):
      '''Returns catalog mask: 1 for objects to keep, 0 for objects to discard.
      Use as:
      maskedQuantity = Quantity[mask]
      '''
      # Here mask is 1 for objects we want to keep
      mask = np.ones_like(self.Catalog.RA)
      #print "keeping fraction", np.sum(mask)/len(mask), " of objects"
      if mVir is not None:
         mask *= (self.Catalog.Mvir>=mVir[0]) * (self.Catalog.Mvir<=mVir[1])
         #print "keeping fraction", np.sum(mask)/len(mask), " of objects"
      if z is not None:
         mask *= (self.Catalog.Z>=z[0]) * (self.Catalog.Z<=z[1])
      if overlap:
         mask *= self.overlapFlag.copy()
         #print "keeping fraction", np.sum(mask)/len(mask), " of objects"
      # PS mask: look at largest aperture, and remove if any point within the disk or ring is masked
      if psMask:
         # The point source mask may vary from one filterType to another
         if filterType is None:
            filterType = self.filtMask.keys()[0]
         mask *= 1.*(np.abs(self.filtMask[filterType][:,-1])<1.)
         #print "keeping fraction", np.sum(mask)/len(mask), " of objects"
      mask *= extraSelection
      #print "keeping fraction", np.sum(mask)/len(mask), " of objects"

      mask = mask.astype(bool)
      #print "keeping fraction", np.sum(mask)/len(mask), " of objects"
      return mask


   ##################################################################################


   def measureVarFromHitCount(self, filterType,  plot=False):
      """Returns a list of functions, one for each AP filter radius,
      where the function takes filtHitNoiseStdDev**2 \propto [(map var) * sr^2] as input and returns the
      actual measured filter variance [(map unit)^2 * sr^2].
      The functions are expected to be linear if the detector noise is the main source of noise,
      and if the hit counts indeed reflect the detector noise.
      To be used for noise weighting in the stacking.
      """
      # keep only objects that overlap, and mask point sources
      mask = self.catalogMask(overlap=True, psMask=True, filterType=filterType)
      # This array contains the true variances for each object and aperture 
      filtVarTrue = np.zeros((self.Catalog.nObj, self.nRAp))

      if self.cmbHit is not None:
         print("Interpolate variance=f(hit count) for each aperture")
         fVarFromHitCount = np.empty(self.nRAp, dtype='object')
         for iRAp in range(self.nRAp):
            x = self.filtHitNoiseStdDev[filterType][mask, iRAp]**2
            y = self.filtMap[filterType][mask, iRAp].copy()
            y = (y - np.mean(y))**2

            # define bins of hit count values
            nBins = 21
            BinsX = np.logspace(np.log10(np.min(x)), np.log10(np.max(x)), nBins, 10.)
            
            # compute histograms
            binCenters, binEdges, binIndices = stats.binned_statistic(x, x, statistic='mean', bins=BinsX)
            binCounts, binEdges, binIndices = stats.binned_statistic(x, x, statistic='count', bins=BinsX)
            binnedVar, binEdges, binIndices = stats.binned_statistic(x, y, statistic=np.mean, bins=BinsX)
            sBinnedVar, binEdges, binIndices = stats.binned_statistic(x, y, statistic=np.std, bins=BinsX)
            sBinnedVar /= np.sqrt(binCounts)
            
            # interpolate, to use as noise weighting
            fVarFromHitCount[iRAp] = interp1d(binCenters, binnedVar, kind='linear', bounds_error=False, fill_value=(binnedVar[0],binnedVar[-1])) 

            # evaluate the variance for each object
            filtVarTrue[mask,iRAp] = fVarFromHitCount[iRAp](x)
            
            if plot:
               # plot
               fig=plt.figure(0)
               ax=fig.add_subplot(111)
               #
               # measured
               ax.errorbar(binCenters, binnedVar*(180.*60./np.pi)**2, yerr=sBinnedVar*(180.*60./np.pi)**2, fmt='.', label=r'measured')
               # interpolated
               newX = np.logspace(np.log10(np.min(x)/2.), np.log10(np.max(x)*2.), 10.*nBins, 10.)
               newY = np.array(map(fVarFromHitCount[iRAp], newX))
               ax.plot(newX, newY*(180.*60./np.pi)**2, label=r'interpolated')
               #
               ax.set_xscale('log', nonposx='clip')
               ax.set_yscale('log', nonposy='clip')
               ax.set_xlabel(r'Det. noise var. from combined hit [arbitrary]')
               ax.set_ylabel(r'Measured var. [$\mu$K.arcmin$^2$]')
               #
               path = self.pathFig+"/binned_noise_vs_hit"+str(iRAp)+".pdf"
               fig.savefig(path, bbox_inches='tight')
               fig.clf()

      else:
         print("Measure var for each aperture (no hit count)")
         meanVarAperture = np.var(self.filtMap[filterType][mask, :], axis=0)
         for iRAp in range(self.nRAp):
            filtVarTrue[mask,iRAp] = meanVarAperture[iRAp] * np.ones(np.sum(mask))

      return filtVarTrue


   def measureAllVarFromHitCount(self, plot=False):
      self.filtVarTrue = {}
      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]
         print("For "+filterType+" filter:")
         self.filtVarTrue[filterType] = self.measureVarFromHitCount(filterType, plot=plot)


   ##################################################################################




   def computeStackedProfile(self, filterType, est, iBootstrap=None, iVShuffle=None, tTh=None, stackedMap=False):
      """Returns the estimated profile and its uncertainty for each aperture.
      est: string to select the estimator
      iBootstrap: index for bootstrap resampling
      iVShuffle: index for shuffling velocities
      tTh: to replace measured temperatures by a theory expectation
      """
      # select objects that overlap, and reject point sources
      mask = self.catalogMask(overlap=True, psMask=True, filterType=filterType)
      
      # temperatures [muK * sr]
      if tTh is None:
         t = self.filtMap[filterType].copy() # [muK * sr]
      elif tTh=='tsz':
         # expected tSZ signal
         # AP profile shape, between 0 and 1
         sigma_cluster = 1.5  # arcmin
         shape = self.ftheoryGaussianProfile(sigma_cluster) # between 0 and 1 [dimless]
         # multiply by integrated y to get y profile [sr]
         t = np.column_stack([self.Catalog.integratedY[:] * shape[iAp] for iAp in range(self.nRAp)])
         # convert from y profile to dT profile
         Tcmb = 2.726   # K
         h = 6.63e-34   # SI
         kB = 1.38e-23  # SI
         def f(nu):
            """frequency dependence for tSZ temperature
            """
            x = h*nu/(kB*Tcmb)
            return x*(np.exp(x)+1.)/(np.exp(x)-1.) -4.
         t *= 2. * f(150.e9) * Tcmb * 1.e6  # [muK * sr]
      elif tTh=='ksz':
         # expected kSZ signal
         # AP profile shape, between 0 and 1
         sigma_cluster = 1.5  # arcmin
         shape = self.ftheoryGaussianProfile(sigma_cluster) # between 0 and 1 [dimless]
         # multiply by integrated kSZ to get kSZ profile [muK * sr]
         t = np.column_stack([self.Catalog.integratedKSZ[:] * shape[iAp] for iAp in range(self.nRAp)])   # [muK * sr]
      t = t[mask, :]
      # v/c [dimless]
      v = -self.Catalog.vR[mask] / 3.e5
      v -= np.mean(v)
      #true filter variance for each object and aperture,
      # valid whether or not a hit count map is available
      s2Full = self.filtVarTrue[filterType][mask, :]
      # Variance from hit count (if available)
      s2Hit = self.filtHitNoiseStdDev[filterType][mask, :]**2
      #print "Shape of s2Hit = ", s2Hit.shape
      # halo masses
      m = self.Catalog.Mvir[mask]
      
      if iBootstrap is not None:
         # make sure each resample is independent,
         # and make the resampling reproducible
         np.random.seed(iBootstrap)
         # list of overlapping objects
         nObj = np.sum(mask)
         I = np.arange(nObj)
         # choose with replacement from this list
         J = np.random.choice(I, size=nObj, replace=True)
         #
         t = t[J,:]
         v = v[J]
         s2Hit = s2Hit[J,:]
         s2Full = s2Full[J,:]
         m = m[J]
      
      if iVShuffle is not None:
         # make sure each shuffling is independent,
         # and make the shuffling reproducible
         np.random.seed(iVShuffle)
         # list of overlapping objects
         nObj = np.sum(mask)
         I = np.arange(nObj)
         # shuffle the velocities
         J = np.random.permutation(I)
         #
         v = v[J]
      
      # tSZ: uniform weighting
      if est=='tsz_uniformweight':
         weights = np.ones_like(s2Hit)
         norm = 1./np.sum(weights, axis=0)
      # tSZ: detector-noise weighted (hit count)
      elif est=='tsz_hitweight':
         weights = 1./s2Hit
         norm = 1./np.sum(weights, axis=0)
      # tSZ: full noise weighted (detector noise + CMB)
      elif est=='tsz_varweight':
         weights = 1./s2Full
         norm = 1./np.sum(weights, axis=0)

      # kSZ: uniform weighting
      elif est=='ksz_uniformweight':
         # remove mean temperature
         t -= np.mean(t, axis=0)
         weights = v[:,np.newaxis] * np.ones_like(s2Hit)
         norm = np.std(v) / np.sum(v[:,np.newaxis]*weights, axis=0)
      # kSZ: detector-noise weighted (hit count)
      elif est=='ksz_hitweight':
         # remove mean temperature
         t -= np.mean(t, axis=0)
         weights = v[:,np.newaxis] / s2Hit
         norm = np.std(v) / np.sum(v[:,np.newaxis]*weights, axis=0)
      # kSZ: full noise weighted (detector noise + CMB)
      elif est=='ksz_varweight':
         # remove mean temperature
         t -= np.mean(t, axis=0)
         weights = v[:,np.newaxis] / s2Full
         norm = np.std(v) / np.sum(v[:,np.newaxis]*weights, axis=0)
      # kSZ: full noise weighted (detector noise + CMB)
      elif est=='ksz_massvarweight':
         # remove mean temperature
         t -= np.mean(t, axis=0)
         weights = m[:,np.newaxis] * v[:,np.newaxis] / s2Full
         norm = np.mean(m) * np.std(v) / np.sum(m[:,np.newaxis]**2 * v[:,np.newaxis]**2 / s2Full, axis=0)


      # return the stacked profiles
      if not stackedMap:
         stack = norm * np.sum(t * weights, axis=0)
         sStack = norm * np.sqrt(np.sum(s2Full * weights**2, axis=0))
         return stack, sStack


      # or, if requested, compute and return the stacked cutout map
      else:
         # define chunks
         nChunk = self.nProc
         chunkSize = self.Catalog.nObj / nChunk
         # list of indices for each of the nChunk chunks
         chunkIndices = [range(iChunk*chunkSize, (iChunk+1)*chunkSize) for iChunk in range(nChunk)]
         # make sure not to miss the last few objects:
         # add them to the last chunk
         chunkIndices[-1] = range((nChunk-1)*chunkSize, self.Catalog.nObj)

         # select weights for a typical aperture size (not the smallest, not the largest)
         iRAp0 = self.nRAp / 2
         norm = norm[iRAp0]
         # need to link object number with weight,
         # despite the mask
         weightsLong = np.zeros(self.Catalog.nObj)
         weightsLong[mask] = weights[:,iRAp0]

         def stackChunk(iChunk):
            # object indices to be processed
            chunk = chunkIndices[iChunk]

            # start with a null map for stacking 
            resMap = self.cutoutGeometry()
            for iObj in chunk:
               if iObj%10000==0:
                  print "- analyze object", iObj
               if self.overlapFlag[iObj]:
                  # Object coordinates
                  ra = self.Catalog.RA[iObj]   # in deg
                  dec = self.Catalog.DEC[iObj] # in deg
                  z = self.Catalog.Z[iObj]
                  # extract postage stamp around it
                  opos, stampMap, stampMask, stampHit = self.extractStamp(ra, dec, test=False)
                  resMap += stampMap * weightsLong[iObj]
            return resMap

         # dispatch each chunk of objects to a different processor
         with sharedmem.MapReduce(np=self.nProc) as pool:
            resMap = np.array(pool.map(stackChunk, range(nChunk)))

         # sum all the chunks
         resMap = np.sum(resMap, axis=0)
         # normalize by the proper sum of weights
         resMap *= norm
         return resMap


   ##################################################################################

   def SaveCovBootstrapStackedProfile(self, filterType, est, nSamples=100, nProc=1):
      """Estimate covariance matrix for the stacked profile from bootstrap resampling
      """
      tStart = time()
      with sharedmem.MapReduce(np=nProc) as pool:
         f = lambda iSample: self.computeStackedProfile(filterType, est, iBootstrap=iSample)
         result = np.array(pool.map(f, range(nSamples)))
         #result = np.array(map(f, range(nSamples)))
      tStop = time()
      print "took", (tStop-tStart)/60., "min"
      # unpack results
      stackSamples = result[:,0,:] # shape (nSamples, nRAp)
      #sStackSamples = result[:,1,:]
      # estimate cov
      covStack = np.cov(stackSamples, rowvar=False)
      # save it to file
      np.savetxt(self.pathOut+"/cov_"+filterType+"_"+est+"_bootstrap.txt", covStack)
      

   def SaveCovVShuffleStackedProfile(self, filterType, est, nSamples=100, nProc=1):
      """Estimate covariance matrix for the stacked profile from shuffling velocities
      """
      tStart = time()
      with sharedmem.MapReduce(np=nProc) as pool:
         f = lambda iSample: self.computeStackedProfile(filterType, est, iVShuffle=iSample)
         result = np.array(pool.map(f, range(nSamples)))
      tStop = time()
      print "took", (tStop-tStart)/60., "min"
      # unpack results
      stackSamples = result[:,0,:] # shape (nSamples, nRAp)
      #sStackSamples = result[:,1,:]
      # estimate cov
      covStack = np.cov(stackSamples, rowvar=False)
      # save it to file
      np.savetxt(self.pathOut+"/cov_"+filterType+"_"+est+"_vshuffle.txt", covStack)


   ##################################################################################


   def saveAllStackedMaps(self, filterTypes=None, Est=None):
      print "- compute stacked maps"
      if filterTypes is None:
         filterTypes = self.filterTypes
      if Est is None:
         Est = self.Est

      # Get cutout geometry, for plotting
      cutoutMap = self.cutoutGeometry()
      size = cutoutMap.posmap()[0,:,:].max() - cutoutMap.posmap()[0,:,:].min()
      baseMap = FlatMap(nX=cutoutMap.shape[0], nY=cutoutMap.shape[1], sizeX=size, sizeY=size)


      # loop over filter types: only matter
      # because they determine the weights in the stacked map
      for iFilterType in range(len(filterTypes)):
         filterType = filterTypes[iFilterType]
         # Estimators (tSZ, kSZ, various weightings...)
         for iEst in range(len(Est)):
            est = Est[iEst]
            print "compute stacked map:", filterType, est
            stackedMap = self.computeStackedProfile(filterType, est, iBootstrap=None, iVShuffle=None, tTh=None, stackedMap=True)
            # plot the stacked map and save it
            path = self.pathFig + "/stackedmap_"+filterType+"_"+est+".pdf"
            baseMap.plot(data=stackedMap, save=True, path=path)


   ##################################################################################


   def saveAllStackedProfiles(self):
      print "- compute stacked profiles and their cov"
      data = np.zeros((self.nRAp, 3))
      data[:,0] = self.RApArcmin # [arcmin]
      
      # Compute all filter types and estimators
      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]

         # Estimators (tSZ, kSZ, various weightings...)
         for iEst in range(len(self.Est)):
            est = self.Est[iEst]
            # measured stacked profile
            data[:,1], data[:,2] = self.computeStackedProfile(filterType, est) # [map unit * sr]
            np.savetxt(self.pathOut+"/"+filterType+"_"+est+"_measured.txt", data)
            # expected stacked profile from tSZ
            data[:,1], data[:,2] = self.computeStackedProfile(filterType, est, tTh='tsz') # [map unit * sr]
            np.savetxt(self.pathOut+"/"+filterType+"_"+est+"_theory_tsz.txt", data)
            # expected stacked profile from kSZ
            data[:,1], data[:,2] = self.computeStackedProfile(filterType, est, tTh='ksz') # [map unit * sr]
            np.savetxt(self.pathOut+"/"+filterType+"_"+est+"_theory_ksz.txt", data)

         # covariance matrices from bootstrap,
         # only for a few select estimators
         for iEst in range(len(self.EstBootstrap)):
            est = self.EstBootstrap[iEst]
            self.SaveCovBootstrapStackedProfile(filterType, est, nSamples=100, nProc=self.nProc)

         # covariance matrices from shuffling velocities,
         # for ksz only
         for iEst in range(len(self.EstVShuffle)):
            est = self.EstVShuffle[iEst]
            self.SaveCovVShuffleStackedProfile(filterType, est, nSamples=100, nProc=self.nProc)


   def loadAllStackedProfiles(self):
      print "- load stacked profiles and their cov"
      self.stackedProfile = {}
      self.sStackedProfile = {}
      self.covBootstrap = {}
      self.covVShuffle = {}
      
      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]

         # all stacked profiles
         for iEst in range(len(self.Est)):
            est = self.Est[iEst]
            # measured stacked profile
            data = np.genfromtxt(self.pathOut+"/"+filterType+"_"+est+"_measured.txt")
            self.stackedProfile[filterType+"_"+est] = data[:,1]
            self.sStackedProfile[filterType+"_"+est] = data[:,2]
            # expected stacked profile from tSZ
            data = np.genfromtxt(self.pathOut+"/"+filterType+"_"+est+"_theory_tsz.txt")
            self.stackedProfile[filterType+"_"+est+"_theory_tsz"] = data[:,1]
            self.sStackedProfile[filterType+"_"+est+"_theory_tsz"] = data[:,2]
            # expected stacked profile from kSZ
            data = np.genfromtxt(self.pathOut+"/"+filterType+"_"+est+"_theory_ksz.txt")
            self.stackedProfile[filterType+"_"+est+"_theory_ksz"] = data[:,1]
            self.sStackedProfile[filterType+"_"+est+"_theory_ksz"] = data[:,2]

         # covariance matrices from bootstrap,
         # only for a few select estimators
         for iEst in range(len(self.EstBootstrap)):
            est = self.EstBootstrap[iEst]
            self.covBootstrap[filterType+"_"+est] = np.genfromtxt(self.pathOut+"/cov_"+filterType+"_"+est+"_bootstrap.txt")
         
         # covariance matrices from shuffling velocities,
         # for ksz only
         for iEst in range(len(self.EstVShuffle)):
            est = self.EstVShuffle[iEst]
            self.covVShuffle[filterType+"_"+est] = np.genfromtxt(self.pathOut+"/cov_"+filterType+"_"+est+"_vshuffle.txt")


   ##################################################################################

   def plotStackedProfile(self, filterType, Est, name=None, pathDir=None, theory=True, tsArr=None, plot=False):
      """Compares stacked profiles, and their uncertainties.
      If pathDir is not specified, save to local figure folder.
      """
      if name is None:
         name = Est[0]
      if tsArr is None:
         tsArr = [self]
      if pathDir is None:
         pathDir = self.pathFig
      
      # stacked profile
      fig=plt.figure(0)
      ax=fig.add_subplot(111)
      #
      # convert from sr to arcmin^2
      factor = (180.*60./np.pi)**2
      #
      ax.axhline(0., c='k', lw=1)
      #
      colors = ['r', 'g', 'b', 'm', 'c']
      lineStyles = ['-', '--', '-.', ':']
      for iEst in range(len(Est)):
         est = Est[iEst]
         c = colors[iEst%len(colors)]

         for iTs in range(len(tsArr)):
            ts = tsArr[iTs]
            ls = lineStyles[iTs%len(tsArr)]

            ax.errorbar(ts.RApArcmin+iTs*0.05, factor * ts.stackedProfile[filterType+"_"+est], factor * ts.sStackedProfile[filterType+"_"+est], fmt=ls, c=c, label=filterType.replace('_',' ')+' '+est.replace('_', ' ')+' '+ts.name.replace('_',' '))
            if theory:
               ax.plot(ts.RApArcmin+iTs*0.05, factor * ts.stackedProfile[filterType+"_"+est+"_theory_tsz"], ls='--', c=c, label="theory tsz, "+filterType.replace('_',' ')+' '+est.replace('_', ' ')+' '+ts.name.replace('_',' '))
               ax.plot(ts.RApArcmin+iTs*0.05, factor * ts.stackedProfile[filterType+"_"+est+"_theory_ksz"], ls='-.', c=c, label="theory ksz, "+filterType.replace('_',' ')+' '+est.replace('_', ' ')+' '+ts.name.replace('_',' '))
      #
      ax.legend(loc=2, fontsize='x-small', labelspacing=0.1)
      ax.set_xlabel(r'$R$ [arcmin]')
      ax.set_ylabel(r'$T$ [$\mu K\cdot\text{arcmin}^2$]')
      #ax.set_ylim((0., 2.))
      #
      path = pathDir+"/"+name+".pdf"
      fig.savefig(path, bbox_inches='tight')
      if plot:
         plt.show()
      fig.clf()



      # uncertainty on stacked profile
      fig=plt.figure(0)
      ax=fig.add_subplot(111)
      #
      # convert from sr to arcmin^2
      factor = (180.*60./np.pi)**2
      #
      colors = ['r', 'g', 'b', 'm', 'c']
      lineStyles = ['-', '--', '-.', ':']
      for iEst in range(len(Est)):
         est = Est[iEst]
         c = colors[iEst%len(colors)]

         for iTs in range(len(tsArr)):
            ts = tsArr[iTs]
            ls = lineStyles[iTs%len(tsArr)]

            ax.plot(ts.RApArcmin+iTs*0.05, factor * ts.sStackedProfile[filterType+"_"+est], c=c, ls=ls, lw=2, label='analytic, '+filterType.replace('_',' ')+' '+est.replace('_', ' ')+' '+ts.name.replace('_',' '))
            if est in ts.covBootstrap:
               ax.plot(ts.RApArcmin+iTs*0.05, factor * np.sqrt(np.diag(ts.covBootstrap[filterType+"_"+est])), c=c, ls=ls, lw=1.5, label="bootstrap, "+filterType.replace('_',' ')+' '+est.replace('_', ' ')+' '+ts.name.replace('_',' '))
            if est in ts.covVShuffle:
               ax.plot(ts.RApArcmin+iTs*0.05, factor * np.sqrt(np.diag(ts.covVShuffle[filterType+"_"+est])), c=c, ls=ls, lw=1, label="v shuffle, "+filterType.replace('_',' ')+' '+est.replace('_', ' ')+' '+ts.name.replace('_',' '))
      #
      ax.legend(loc=2, fontsize='x-small', labelspacing=0.1)
      ax.set_xlabel(r'$R$ [arcmin]')
      ax.set_ylabel(r'$\sigma(T)$ [$\mu K\cdot\text{arcmin}^2$]')
      #ax.set_ylim((0., 2.))
      #
      path = pathDir+"/s_"+name+".pdf"
      fig.savefig(path, bbox_inches='tight')
      if plot:
         plt.show()
      fig.clf()


   def plotAllStackedProfiles(self):
      print "- plot all stacked profiles"
      
      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]
         # all stacked profiles
         for iEst in range(len(self.Est)):
            est = self.Est[iEst]
            self.plotStackedProfile(filterType, [est], name=filterType+"_"+est)

   ##################################################################################
   
   def plotCov(self, cov, name="", show=False):
      # Covariance matrix
      fig=plt.figure(0)
      ax=fig.add_subplot(111)
      #
      # pcolor wants x and y to be edges of cell,
      # ie one more element, and offset by half a cell
      dR = (self.rApMaxArcmin - self.rApMinArcmin) / self.nRAp
      RApEdgesArcmin = np.linspace(self.rApMinArcmin-0.5*dR, self.rApMaxArcmin+0.5*dR, self.nRAp+1)
      # Covariance  matrix
      X, Y = np.meshgrid(RApEdgesArcmin, RApEdgesArcmin, indexing='ij')
      cp=ax.pcolormesh(X, Y, cov, cmap='YlOrRd')
      #
      ax.set_aspect('equal')
      plt.colorbar(cp)
      ax.set_xlim((np.min(RApEdgesArcmin), np.max(RApEdgesArcmin)))
      ax.set_ylim((np.min(RApEdgesArcmin), np.max(RApEdgesArcmin)))
      ax.set_xlabel(r'R [arcmin]')
      ax.set_ylabel(r'R [arcmin]')
      #
      path = self.pathFig+"/cov_"+name+".pdf"
      fig.savefig(path, bbox_inches='tight')
      if show:
         plt.show()
      else:
         fig.clf()
      

      # Correlation coefficient
      fig=plt.figure(1)
      ax=fig.add_subplot(111)
      #
      # pcolor wants x and y to be edges of cell,
      # ie one more element, and offset by half a cell
      dR = (self.rApMaxArcmin - self.rApMinArcmin) / self.nRAp
      RApEdgesArcmin = np.linspace(self.rApMinArcmin-0.5*dR, self.rApMaxArcmin+0.5*dR, self.nRAp+1)
      X, Y = np.meshgrid(RApEdgesArcmin, RApEdgesArcmin, indexing='ij')
      #
      sigma = np.sqrt(np.diag(cov))
      cor = np.array([[cov[i1, i2] / (sigma[i1]*sigma[i2]) for i2 in range(self.nRAp)] for i1 in range(self.nRAp)])
      cp=ax.pcolormesh(X, Y, cor, cmap='YlOrRd', vmin=0., vmax=1.)
      #
      ax.set_aspect('equal')
      plt.colorbar(cp)
      ax.set_xlim((np.min(RApEdgesArcmin), np.max(RApEdgesArcmin)))
      ax.set_ylim((np.min(RApEdgesArcmin), np.max(RApEdgesArcmin)))
      ax.set_xlabel(r'R [arcmin]')
      ax.set_ylabel(r'R [arcmin]')
      #
      path = self.pathFig+"/cor_"+name+".pdf"
      fig.savefig(path, bbox_inches='tight')
      if show:
         plt.show()
      else:
         fig.clf()


   def plotAllCov(self):
      print "- plot all covariances"
      for iFilterType in range(len(self.filterTypes)):
         filterType = self.filterTypes[iFilterType]

         # covariance matrices from bootstrap,
         # only for a few select estimators
         for iEst in range(len(self.EstBootstrap)):
            est = self.EstBootstrap[iEst]
            self.plotCov(self.covBootstrap[filterType+"_"+est], filterType+"_"+est+"_bootstrap")
         
         # covariance matrices from shuffling velocities,
         # for ksz only
         for iEst in range(len(self.EstVShuffle)):
            est = self.EstVShuffle[iEst]
            self.plotCov(self.covVShuffle[filterType+"_"+est], filterType+"_"+est+"_vshuffle")


   ##################################################################################

   def ftheoryGaussianProfile(self, sigma_cluster, filterType='diskring'):
      """Alpha_ksz signal, between 0 and 1.
      Assumes that the projected cluster profile is a 2d Gaussian,
      with sigma_cluster in arcmin
      Assumes equal area disk-ring filter
      """
      if filterType=='diskring':
         result = (1. - np.exp(-0.5*self.RApArcmin**2/sigma_cluster**2))**2
      elif filterType=='disk':
         result = 1. - np.exp(-0.5*self.RApArcmin**2/sigma_cluster**2)
      elif filterType=='ring':
         result = np.exp(-0.5*self.RApArcmin**2/sigma_cluster**2) - np.exp(-0.5*(self.RApArcmin*np.sqrt(2.))**2/sigma_cluster**2)
      return result



   def ftheoryGaussianProfilePixelated(self, sigma_cluster=1.5, filterType='diskring', dxDeg=0.3, dyDeg= 0.3, resArcmin=0.25, proj='cea', pixwin=0, test=False):
      """Alpha_ksz signal, between 0 and 1.
      Assumes that the projected cluster profile is a 2d Gaussian,
      with sigma_cluster in arcmin
      Assumes equal area disk-ring filter.
      This version is not analytical, but instead generates a mock cutout map
      with a Gaussian profile, and runs the AP filters on it.
      This takes into account the discreteness of the edges of the AP filters
      due to the pixelation of the map
      """

      ###########################################
      # generate pixellized cluster profile map

      # generate null cutout map
      stampMap = self.cutoutGeometry()
      opos = stampMap.posmap()

      # fill the central pixel
      ra = 0.
      dec = 0.
      # coordinates in [rad]
      sourcecoord = np.array([dec, ra]) * np.pi/180.
      # find pixel indices (float) corresponding to ra, dec
      iY, iX = enmap.sky2pix(shape, wcs, sourcecoord, safe=True, corner=False)
      # nearest pixel
      jY = np.int(round(iY))
      jX = np.int(round(iX))
      # fill in the central pixel
      # and normalize to integrate to 1 over angles in [muK*sr]
      pixSizeMap = stampMap.pixsizemap()
      stampMap[jY, jX] = 1. / pixSizeMap[jY, jX] # divide by pixel area in sr

      # convolve map with a Gaussian  profile of given sigma (not fwhm)
      stampMap = enmap.smooth_gauss(stampMap, sigma_cluster * np.pi/180./60.) # convert from arcmin to [rad]

      # apply the pixel window function if desired
      if pixwin<>0:
         stampMap = enmap.apply_window(stampMap, pow=pixwin)


      ###########################################
      # perform the AP filtering

      # create arrays of filter values for the given object
      filtMap = np.zeros(self.nRAp)
  
      # loop over the radii for the AP filter
      for iRAp in range(self.nRAp):
         # Disk radius in rad
         r0 = self.RApArcmin[iRAp] / 60. * np.pi/180.
         # choose an equal area AP filter
         r1 = r0 * np.sqrt(2.)
         
         # perform the filtering
         filtMap[iRAp],_,_,_ = self.aperturePhotometryFilter(opos, stampMap, stampMap, stampMap, r0, r1, filterType=filterType, test=False)
      
      
      if test:
         # compare to the non-pixelated theory profile
         nonPixelated = self.ftheoryGaussianProfile(sigma_cluster, filterType=filterType)
         
         fig=plt.figure(0)
         ax=fig.add_subplot(111)
         #
         ax.plot(self.RApArcmin, nonPixelated, 'k-', label=r'Analytical')
         ax.plot(self.RApArcmin, filtMap, 'b--', label=r'Pixelated')
         #
         ax.legend(loc=4, fontsize='x-small', labelspacing=0.1)
         
         plt.show()
      
      
      return filtMap


   ##################################################################################


   def computeSnrStack(self, filterType, est, tTh=None):
      """Compute null rejection, SNR (=detection significance)
      for the requested estimator.
      The estimator considered should have a bootstrap covariance.
      """


      # replace data with theory if requested
      if tTh=='tsz':
         tTh = '_theory_tsz'
      elif tTh=='ksz':
         tTh = '_theory_ksz'
      else:
         tTh = ''

      path = self.pathFig+"/snr_"+filterType+"_"+est+tTh+".txt"
      with open(path, 'w') as f:
         f.write("*** "+est+" SNR ***\n")

         # data and covariance
         d = self.stackedProfile[filterType+"_"+est+tTh].copy()
         cov = self.covBootstrap[filterType+"_"+est].copy()
         dof = len(d)

         # Compute chi^2_null
         chi2Null = d.dot( np.linalg.inv(cov).dot(d) )
         # goodness of fit for null hypothesis
         f.write("number of dof:"+str(dof)+"\n")
         f.write("null chi2Null="+str(chi2Null)+"\n")
         pteNull = 1.- stats.chi2.cdf(chi2Null, dof)
         f.write("null pte="+str(pteNull)+"\n")
         # pte as a function of sigma, for a Gaussian random variable
         fsigmaToPTE = lambda sigma: special.erfc(sigma/np.sqrt(2.)) - pteNull
         sigmaNull = optimize.brentq(fsigmaToPTE , 0., 1.e3)
         f.write("null pte significance="+str(sigmaNull)+"sigmas\n\n")

         # Gaussian model: find best fit amplitude
         sigma_cluster = 1.5  # arcmin
         theory = self.ftheoryGaussianProfile(sigma_cluster, filterType=filterType)
         def fdchi2(p):
            a = p[0]
            result = (d-a*theory).dot( np.linalg.inv(cov).dot(d-a*theory) )
            result -= chi2Null
            return result
         # Minimize the chi squared
         p0 = 1.
         res = optimize.minimize(fdchi2, p0)
         abest = res.x[0]
         #sbest= res.x[1]
         f.write("best-fit amplitude="+str(abest)+"\n")
         f.write("number of dof:"+str(dof - 1)+"\n\n")

         # goodness of fit for best fit
         chi2Best = fdchi2([abest])+chi2Null
         f.write("best-fit chi2="+str(chi2Best)+"\n")
         pteBest = 1.- stats.chi2.cdf(chi2Best, dof-1.)
         f.write("best-fit pte="+str(pteBest)+"\n")
         # pte as a function of sigma, for a Gaussian random variable
         fsigmaToPTE = lambda sigma: special.erfc(sigma/np.sqrt(2.)) - pteBest
         sigma = optimize.brentq(fsigmaToPTE , 0., 1.e3)
         f.write("best-fit pte significance="+str(sigma)+"sigmas\n\n")

         # favour of best fit over null
         f.write("best-fit sqrt(delta chi2)="+str(np.sqrt(abs(fdchi2([abest]))))+"sigmas\n")
         fsigmaToPTE = lambda sigma: special.erfc(sigma/np.sqrt(2.))
         pte = fsigmaToPTE( np.sqrt(abs(fdchi2([abest]))) )
         f.write("pte (if Gaussian)="+str(pte)+"\n")


   def computeAllSnr(self):
      print "- compute all SNR and significances"
      for filterType in self.filterTypes:
         for est in self.EstBootstrap:
            self.computeSnrStack(filterType, est)
            self.computeSnrStack(filterType, est, tTh='tsz')
            self.computeSnrStack(filterType, est, tTh='ksz')



   ##################################################################################





