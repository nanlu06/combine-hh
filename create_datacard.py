from __future__ import print_function, division
import os
import rhalphalib as rl
import numpy as np
import pickle
import uproot
rl.util.install_roofit_helpers()
rl.ParametericSample.PreferRooParametricHist = False


def get_hist(inputfile, name, obs):
    upfile = uproot.open(inputfile)
    hist_values = upfile[name].values()
    hist_edges = upfile[name].axis().edges()
    hist_uncs = upfile[name].variances()
    if obs.binning != hist_edges:
        # rebin (assumes new bins are a subset of existing bins)
        edge_mask = np.in1d(hist_edges, obs.binning)
        hist_mask = np.logical_and(edge_mask[0:-1], edge_mask[1:])
        hist_values = hist_values[hist_mask]
        hist_edges = hist_edges[edge_mask]
        hist_uncs = hist_uncs[hist_mask]
    return (hist_values, hist_edges, obs.name, hist_uncs)


def create_datacard(inputfile, carddir, nbins, nMCTF, nDataTF, passBinName, failBinName='fail', add_blinded=False, include_ac=False):

    regionPairs = [('SR'+passBinName, 'fit'+failBinName)]  # pass, fail region pairs
    if add_blinded:
        regionPairs += [('pass'+passBinName, failBinName)]  # add sideband region pairs

    regions = [item for t in regionPairs for item in t]  # all regions

    # luminosity unc https://gitlab.cern.ch/hh/naming-conventions#luminosity
    lumi_13TeV_2016 = rl.NuisanceParameter('lumi_13TeV_2016', 'lnN')
    lumi_13TeV_2017 = rl.NuisanceParameter('lumi_13TeV_2017', 'lnN')
    lumi_13TeV_2018 = rl.NuisanceParameter('lumi_13TeV_2018', 'lnN')
    lumi_13TeV_correlated = rl.NuisanceParameter('lumi_13TeV_correlated', 'lnN')
    lumi_13TeV_1718 = rl.NuisanceParameter('lumi_13TeV_1718', 'lnN')
    ttbarBin1MCstats = rl.NuisanceParameter('CMS_bbbb_boosted_ggf_ttbarBin1_yieldMCStats', 'lnN')
    PNetHbbScaleFactorssyst = rl.NuisanceParameter('CMS_bbbb_boosted_ggf_PNetHbbScaleFactors_correlated', 'lnN')
    brHbb = rl.NuisanceParameter('BR_hbb', 'lnN')
    pdfqqbar = rl.NuisanceParameter('pdf_Higgs_qqbar', 'lnN')
    pdfttH = rl.NuisanceParameter('pdf_Higgs_ttH', 'lnN')
    pdfggHH = rl.NuisanceParameter('pdf_Higgs_ggHH', 'lnN')
    pdfqqHH = rl.NuisanceParameter('pdf_Higgs_qqHH', 'lnN')
    qcdScaleVH = rl.NuisanceParameter('QCDscale_VH', 'lnN')
    qcdScalettH = rl.NuisanceParameter('QCDscale_ttH', 'lnN')
    qcdScaleqqHH = rl.NuisanceParameter('QCDscale_qqHH', 'lnN')
    alphaS = rl.NuisanceParameter('alpha_s', 'lnN')
    fsrothers = rl.NuisanceParameter('ps_fsr_others', 'lnN')
    isrothers = rl.NuisanceParameter('ps_isr_others', 'lnN')
    if not include_ac:
        thu_hh = rl.NuisanceParameter('THU_SMHH', 'lnN')

    msdbins = np.linspace(50, nbins*10.0+50.0, nbins+1)
    msd = rl.Observable('msd', msdbins)
    msdpts = msdbins[:-1] + 0.5 * np.diff(msdbins)
    msdscaled = (msdpts - 50.)/(10.0*nbins)

    # Build qcd MC pass+fail model and fit to polynomial
    qcdmodel = rl.Model('qcdmodel')
    qcdpass, qcdfitfail = 0., 0.
    passCh = rl.Channel('passqcdmodel')
    fitfailCh = rl.Channel('fitfailqcdmodel')
    qcdmodel.addChannel(fitfailCh)
    qcdmodel.addChannel(passCh)

    passTempl = get_hist(inputfile, 'histJet2MassBlind_'+passBinName+'_QCD', obs=msd)
    fitfailTempl = get_hist(inputfile, 'histJet2Massfit_fail_QCD', obs=msd)

    passCh.setObservation(passTempl[:-1])
    fitfailCh.setObservation(fitfailTempl[:-1])
    qcdpass = passCh.getObservation().sum()
    qcdfitfail = fitfailCh.getObservation().sum()

    qcdeffpass = qcdpass / qcdfitfail

    # transfer factor
    tf_dataResidual = rl.BernsteinPoly("CMS_bbbb_boosted_ggf_tf_dataResidual_"+passBinName, (nDataTF,), ['msd'], limits=(-20, 20))
    tf_dataResidual_params = tf_dataResidual(msdscaled)
    tf_params_pass = qcdeffpass * tf_dataResidual_params

    # qcd params
    qcdparams = np.array([rl.IndependentParameter('CMS_bbbb_boosted_ggf_qcdparam_msdbin%d' % i, 0) for i in range(msd.nbins)])

    # build actual fit model now
    model = rl.Model("HHModel")
    for region in regions:
        print('INFO: starting region: %s' % region)
        ch = rl.Channel(region)
        model.addChannel(ch)

        if region == 'pass'+passBinName:
            catn = 'Blind_'+passBinName
        elif region == 'SR'+passBinName:
            catn = '_'+passBinName
        elif region == 'fit'+failBinName:
            catn = 'fit_'+failBinName
        else:
            catn = 'Blind_'+failBinName

        # dictionary of name in datacards -> name in ROOT file
        templateNames = {
            'ttbar': 'histJet2Mass'+catn+'_TTJets',
            'ggHH_kl_1_kt_1_hbbhbb': 'histJet2Mass'+catn+'_ggHH_kl_1_kt_1_boost4b',
            'qqHH_CV_1_C2V_1_kl_1_hbbhbb': 'histJet2Mass'+catn+'_qqHH_CV_1_C2V_1_kl_1_boost4b',
            'VH_hbb': 'histJet2Mass'+catn+'_VH',
            'ttH_hbb': 'histJet2Mass'+catn+'_ttH',
            'bbbb_boosted_ggf_others': 'histJet2Mass'+catn+'_others',
            'bbbb_boosted_ggf_qcd_datadriven': 'histJet2Mass'+catn+'_QCD',
            'data': 'histJet2Mass'+catn+'_Data',
        }

        if include_ac:
            templateNames.update({
                'ggHH_kl_2p45_kt_1_hbbhbb': 'histJet2Mass'+catn+'_ggHH_kl_2p45_kt_1_boost4b',
                'ggHH_kl_5_kt_1_hbbhbb': 'histJet2Mass'+catn+'_ggHH_kl_5_kt_1_boost4b',
                'qqHH_CV_1_C2V_0_kl_1_hbbhbb': 'histJet2Mass'+catn+'_qqHH_CV_1_C2V_0_kl_1_boost4b',
                'qqHH_CV_1p5_C2V_1_kl_1_hbbhbb': 'histJet2Mass'+catn+'_qqHH_CV_1p5_C2V_1_kl_1_boost4b',
                'qqHH_CV_1_C2V_1_kl_2_hbbhbb': 'histJet2Mass'+catn+'_qqHH_CV_1_C2V_1_kl_2_boost4b',
                'qqHH_CV_1_C2V_2_kl_1_hbbhbb': 'histJet2Mass'+catn+'_qqHH_CV_1_C2V_2_kl_1_boost4b',
                'qqHH_CV_1_C2V_1_kl_0_hbbhbb': 'histJet2Mass'+catn+'_qqHH_CV_1_C2V_1_kl_0_boost4b',
            })

        templates = {}
        for temp in templateNames:
            templates[temp] = get_hist(inputfile, templateNames[temp], obs=msd)

        # dictionary of systematics -> name in cards
        systs = {
            'ttbarBin1Jet2PNetCut': 'CMS_bbbb_boosted_ggf_ttbarBin1Jet2PNetCut',
            'FSRPartonShower': 'ps_fsr',
            'ISRPartonShower': 'ps_isr',
            'ggHHPDFacc': 'CMS_bbbb_boosted_ggf_ggHHPDFacc',
            'ggHHQCDacc': 'CMS_bbbb_boosted_ggf_ggHHQCDacc',
            'othersQCD': 'CMS_bbbb_boosted_ggf_othersQCD',
            'pileupWeight2016': 'CMS_pileup_2016',
            'pileupWeight2017': 'CMS_pileup_2017',
            'pileupWeight2018': 'CMS_pileup_2018',
            'JER2016': 'CMS_res_j_2016',
            'JER2017': 'CMS_res_j_2017',
            'JER2018': 'CMS_res_j_2018',
            'JES': 'CMS_bbbb_boosted_ggf_scale_j',
            'JMS2016': 'CMS_bbbb_boosted_jms_2016',
            'JMS2017': 'CMS_bbbb_boosted_jms_2017',
            'JMS2018': 'CMS_bbbb_boosted_jms_2018',
            'JMR': 'CMS_bbbb_boosted_jmr',
            # 'JMR2016': 'CMS_bbbb_boosted_jmr_2016',
            # 'JMR2017': 'CMS_bbbb_boosted_jmr_2017',
            # 'JMR2018': 'CMS_bbbb_boosted_jmr_2018',
            'ttJetsCorr': 'CMS_bbbb_boosted_ggf_ttJetsCorr',
            'BDTShape': 'CMS_bbbb_boosted_ggf_ttJetsBDTShape',
            'PNetShape': 'CMS_bbbb_boosted_ggf_ttJetsPNetShape',
            'PNetHbbScaleFactors': 'CMS_bbbb_boosted_ggf_PNetHbbScaleFactors_uncorrelated',
            'triggerEffSF': 'CMS_bbbb_boosted_ggf_triggerEffSF_uncorrelated',
            'trigCorrHH2016': 'CMS_bbbb_boosted_ggf_trigCorrHH2016',
            'trigCorrHH2017': 'CMS_bbbb_boosted_ggf_trigCorrHH2017',
            'trigCorrHH2018': 'CMS_bbbb_boosted_ggf_trigCorrHH2018'
        }

        syst_param_array = []
        for syst in systs:
            syst_param_array.append(rl.NuisanceParameter(systs[syst], 'shape'))

        sNames = [proc for proc in templates.keys() if proc not in ['bbbb_boosted_ggf_qcd_datadriven', 'data']]
        for sName in sNames:
            print('INFO: get templates for: %s' % sName)
            # get templates
            templ = templates[sName]
            stype = rl.Sample.SIGNAL if 'HH' in sName else rl.Sample.BACKGROUND
            sample = rl.TemplateSample(ch.name + '_' + sName, stype, templ)
            sample.setParamEffect(lumi_13TeV_2016, 1.0026)  # 36330.0/137650.0*0.01+1
            sample.setParamEffect(lumi_13TeV_2017, 1.0060)  # 41480.0/137650.0*0.02+1
            sample.setParamEffect(lumi_13TeV_2018, 1.0065)  # 59830.0/137650.0*0.015+1
            sample.setParamEffect(lumi_13TeV_correlated, 1.0130)  # 59830.0/137650.0*0.020+41480.0/137650.0*0.009+0.006*36330.0/137650.0+1
            sample.setParamEffect(lumi_13TeV_1718, 1.0118)  # 59830.0/137650.0*0.016+41480.0/137650.0*0.016+1
            if not include_ac:
                if sName == "ggHH_kl_1_kt_1_hbbhbb":
                    sample.setParamEffect(thu_hh, 0.7822, 1.0556)

            if sName == "bbbb_boosted_ggf_others":
                if "Bin1" in region:
                    sample.setParamEffect(fsrothers, 0.82, 1.06)
                    sample.setParamEffect(isrothers, 0.94, 1.05)
                elif "Bin2" in region:
                    sample.setParamEffect(fsrothers, 0.90, 1.02)
                    sample.setParamEffect(isrothers, 0.93, 1.07)
                elif "Bin3" in region:
                    sample.setParamEffect(fsrothers, 0.91, 1.02)
                    sample.setParamEffect(isrothers, 0.93, 1.06)
                elif "fail" in region:
                    sample.setParamEffect(fsrothers, 0.92, 1.05)
                    sample.setParamEffect(isrothers, 0.94, 1.05)

            if sName == "ttbar" and "Bin1" in region:
                if region == "passBin1":
                    sample.setParamEffect(ttbarBin1MCstats, 1.215)
                elif region == "SRBin1":
                    sample.setParamEffect(ttbarBin1MCstats, 1.187)

            if ("VH" in sName) or ("ttH" in sName):
                sample.setParamEffect(PNetHbbScaleFactorssyst, 1.04)
            elif "HH" in sName:
                sample.setParamEffect(PNetHbbScaleFactorssyst, 1.0816)

            if "hbbhbb" in sName:
                sample.setParamEffect(brHbb, 1.0248, 0.9748)
            elif "hbb" in sName:
                sample.setParamEffect(brHbb, 1.0124, 0.9874)

            if "ttH" in sName:
                sample.setParamEffect(pdfttH, 1.030)
                sample.setParamEffect(qcdScalettH, 1.058, 0.908)
                sample.setParamEffect(alphaS, 1.020)
            elif "VH" in sName:
                sample.setParamEffect(pdfqqbar, 1.0154)
                sample.setParamEffect(qcdScaleVH, 1.0179, 0.9840)
                sample.setParamEffect(alphaS, 1.009)
            elif "ggHH" in sName:
                sample.setParamEffect(pdfggHH, 1.030)
            elif "qqHH" in sName:
                sample.setParamEffect(pdfqqHH, 1.021)
                sample.setParamEffect(qcdScaleqqHH, 1.0003, 0.9996)

            # set mc stat uncs
            print('INFO: setting autoMCStats for %s' % sName)
            sample.autoMCStats()

            # shape systematics
            valuesNominal = templ[0]

            for isyst, syst in enumerate(systs):
                print('INFO: setting shape effect %s for %s' % (syst, sName))
                valuesUp = get_hist(inputfile, '%s_%sUp' % (templateNames[sName], syst), obs=msd)[0]
                valuesDown = get_hist(inputfile, '%s_%sDown' % (templateNames[sName], syst), obs=msd)[0]
                effectUp = np.ones_like(valuesNominal)
                effectDown = np.ones_like(valuesNominal)
                for i in range(len(valuesNominal)):
                    if valuesNominal[i] > 0.:
                        effectUp[i] = valuesUp[i]/valuesNominal[i]
                        effectDown[i] = valuesDown[i]/valuesNominal[i]
                sample.setParamEffect(syst_param_array[isyst], effectUp, effectDown)
            ch.addSample(sample)

        # data observed
        yields = templates['data'][0]
        data_obs = (yields, msd.binning, msd.name)
        ch.setObservation(data_obs)

    for passChName, failChName in regionPairs:
        print('INFO: setting transfer factor for pass region %s, fail region %s' % (passChName, failChName))
        failCh = model[failChName]
        passCh = model[passChName]

        # sideband fail
        initial_qcd = failCh.getObservation().astype(float)  # was integer, and numpy complained about subtracting float from it
        for sample in failCh:
            initial_qcd -= sample.getExpectation(nominal=True)
        if np.any(initial_qcd < 0.):
            raise ValueError("initial_qcd negative for some bins..", initial_qcd)
        sigmascale = 10  # to scale the deviation from initial
        scaledparams = initial_qcd * (1 + sigmascale/np.maximum(1., np.sqrt(initial_qcd)))**qcdparams

        # add samples
        fail_qcd = rl.ParametericSample(failChName+'_bbbb_boosted_ggf_qcd_datadriven', rl.Sample.BACKGROUND, msd, scaledparams)
        failCh.addSample(fail_qcd)

        pass_qcd = rl.TransferFactorSample(passChName+'_bbbb_boosted_ggf_qcd_datadriven', rl.Sample.BACKGROUND, tf_params_pass, fail_qcd)
        passCh.addSample(pass_qcd)

    with open(os.path.join(str(carddir), 'HHModel.pkl'), "wb") as fout:
        pickle.dump(model, fout)

    print('INFO: rendering combine model')
    model.renderCombine(os.path.join(str(carddir), 'HHModel'))


if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--inputfile', default='HHTo4BPlots_Run2_BDTv8p2_0311_syst_Trigv0.root', type=str, dest='inputfile', help='input ROOT file')
    parser.add_argument('--carddir', default='cards', type=str, dest='carddir', help='output card directory')
    parser.add_argument('--nbins', default=17, type=int, dest='nbins', help='number of bins')
    parser.add_argument('--nMCTF', default=0, type=int, dest='nMCTF', help='order of polynomial for TF from MC')
    parser.add_argument('--nDataTF', default=2, type=int, dest='nDataTF', help='order of polynomial for TF from Data')
    parser.add_argument('--passBinName', default='Bin1', type=str, choices=['Bin1', 'Bin2', 'Bin3'], help='pass bin name')
    parser.add_argument('--blinded', action='store_true', help='run on data on SR')
    args = parser.parse_args()
    if not os.path.exists(args.carddir):
        os.mkdir(args.carddir)
    print(args.blinded)
    create_datacard(args.inputfile, args.carddir, args.nbins, args.nMCTF, args.nDataTF, args.passBinName, "fail", args.blinded)
