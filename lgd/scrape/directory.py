import os
import os.path
import io
import time
import logging

from datetime import datetime, timedelta
from pathlib import Path
from .base import (INCORRECT_CAPTCHA_MESSAGE,
                   DownloaderItem, BaseDownloader,
                   MultiDownloader)
from .conversion_helper import (records_from_excel, records_from_xslx,
                                unzip_single, records_from_odt)

logger = logging.getLogger(__name__)

def merge_file(old_file, mod_file, tgt_file):
    #TODO: write this
    pass



class DirectoryDownloader(BaseDownloader):
    def __init__(self, post_data_extra={}, odt_conv_args={}, **kwargs):
        kwargs['section'] = 'Download Directory'
        super().__init__(**kwargs)
        self.post_data = {
            "DDOption": "UNSELECT",
            "downloadOption": "DFD",
            "entityCode": "-1",
            "_multiRptFileNames": ["on"] * 12,
            "fromDate": None,
            "toDate": None,
            "fromDate2": None,
            "toDate2": None,
            "rptFileNameMod": "0",
            "entityCodes": [ '35', None ],
            "stateName": [ 'ANDAMAN AND NICOBAR ISLANDS', None, None ],
            "districtName": [ None ] * 3,
            "blockName": [ None ] * 3,
            "lbl": None,
            "downloadType": "xls",
        }
        self.post_data.update(post_data_extra)
        self.odt_conv_args = odt_conv_args

    def set_context(self, ctx):
        if ctx.csrf_token is not None:
            self.post_data['OWASP_CSRFTOKEN'] = ctx.csrf_token
        super().set_context(ctx)


    def get_records(self):
        count = 0
        download_dir_url = '{}/downloadDirectory.do?OWASP_CSRFTOKEN={}'.format(self.base_url, self.ctx.csrf_token)
        while True:
            captcha_code = self.captcha_helper.get_code(download_dir_url)
            self.post_data['captchaAnswer'] = captcha_code
            post_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'referer': download_dir_url
            }
            web_data = self.post_with_progress(download_dir_url,
                                               data=self.post_data,
                                               headers=post_headers)
            if not web_data.ok:
                raise Exception('bad web request.. {}: {}'.format(web_data.status_code, web_data.text))
                
            if web_data.headers['Content-Type'] == 'text/html;charset=UTF-8':
                if INCORRECT_CAPTCHA_MESSAGE  not in web_data.text:
                    if self.params.save_failed_html:
                        with open('failed.html', 'w') as f:
                            f.write(web_data.text)
                    raise Exception('Non-captcha failure in request')
    
                self.captcha_helper.mark_failure()
                if count > 5:
                    raise Exception('failed after trying for 5 times')
                time.sleep(1)
                count += 1
                continue
    
            self.captcha_helper.mark_success()
            data_file = None
            is_xlsx = False
            is_odt = False
            if web_data.headers['Content-Type'] == 'application/zip;charset=UTF-8':
                logger.debug('unzipping data')
                filename, content = unzip_single(web_data.content)
                logger.debug(f'unzipped filename: {filename}')
                if filename.endswith('.xlsx'):
                    is_xlsx = True
                if filename.endswith('.odt'):
                    is_odt = True
                data_file = io.BytesIO(content)
    
            if web_data.headers['Content-Type'] == 'odt;charset=UTF-8':
                data_file = io.BytesIO(web_data.content)
                is_odt = True

            if web_data.headers['Content-Type'] == 'xls;charset=UTF-8':
                data_file = io.BytesIO(web_data.content)
    
            if web_data.headers['Content-Type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;charset=UTF-8':
                data_file = io.BytesIO(web_data.content)
                is_xlsx = True
            
            #print(web_data.headers['Content-Type'])
    
            if data_file is None:
                raise Exception("no data file available")
    
            records = []
            if is_xlsx:
                records = records_from_xslx(data_file)
            elif is_odt:
                #with open('temp_{}.odt'.format(self.name), 'wb') as f:
                #    f.write(data_file.getvalue())
                records = records_from_odt(data_file, **self.odt_conv_args)
            else:
                records = records_from_excel(data_file)

            #logger.debug('got {} records'.format(len(records)))
            #logger.debug('{}'.format(records[0]))
            return records


    #TODO: this is incomplete
    def get_file_mod(self):
    
        if not self.params.using_mods:
            self.get_file()
            return
    
        csv_filename = self.get_filename()
        dir_name = os.path.dirname(csv_filename)
        file_name = os.path.basename(csv_filename)
        old_csv_filename = csv_filename
        csv_filename = f'{dir_name}/mods/{file_name}'
        self.post_data['downloadOption'] = 'DMO'
        self.post_data['rptFileNameMod'] = self.post_data['rptFileName'] + 'byDate' 
        self.post_data['rptFileName'] = '-1'
        self.post_data['fromDate'] = MOD_FROM_DATE
        self.post_data['toDate'] = MOD_TO_DATE
        dir_dir_name = os.path.dirname(dir_name)
        old_file = f'{dir_dir_name}/{MOD_FROM_DATE}/{file_name}'
    
        if os.path.exists(csv_filename):
            merge_file(old_file, csv_filename, old_csv_filename) 
            os.remove(csv_filename)
            return
    
        # TODO: use changed filename
        self.get_file()
        merge_file(old_file, csv_filename, old_csv_filename) 
        os.remove(csv_filename)





class StateWiseDirectoryDownloader(MultiDownloader, DirectoryDownloader):
    def __init__(self, **kwargs):
        if 'enrichers' not in kwargs:
            kwargs['enrichers'] = { 'State Code': 'State Code',
                                    'State Name': 'State Name(In English)' }
        if 'deps' not in kwargs:
            kwargs['deps'] = []
        if 'STATES' not in kwargs['deps']:
            kwargs['deps'].append('STATES')
        super().__init__(**kwargs)
        self.post_data_extra = kwargs.get('post_data_extra', {})

    def populate_downloaders(self):
        if self.downloader_items is not None:
            return
        downloader_items = []
        for r in BaseDownloader.records_from_downloader('STATES'):
            state_code = r['State Code']
            state_name = r['State Name(In English)']

            csv_path = Path(self.csv_filename)
            csv_filename_s = str(csv_path.with_stem('{}_{}'.format(csv_path.stem, state_code)))
            downloader = DirectoryDownloader(name='{}_{}'.format(self.name, state_code),
                                             desc='{} for state {}({})'.format(self.desc, state_name, state_code),
                                             csv_filename=csv_filename_s,
                                             params=self.params,
                                             ctx=self.ctx,
                                             transform=self.transform,
                                             odt_conv_args=self.odt_conv_args,
                                             post_data_extra=self.post_data_extra | {
                                                 'stateName': state_name,
                                                 'entityCodes': state_code
                                             })
            downloader_items.append(DownloaderItem(downloader=downloader, record=r))
        self.downloader_items = downloader_items


class OrgWiseDirectoryDownloader(MultiDownloader, DirectoryDownloader):
    def __init__(self, depends_on='', **kwargs):
        if 'deps' not in kwargs:
            kwargs['deps'] = []

        if depends_on != '' and depends_on not in kwargs['deps']:
            kwargs['deps'].append(depends_on)
        super().__init__(**kwargs)
        self.depends_on = depends_on
        self.post_data_extra = kwargs.get('post_data_extra', {})

    def populate_downloaders(self):
        if self.downloader_items is not None:
            return

        downloader_items = []
        for r in BaseDownloader.records_from_downloader(self.depends_on):
            org_code = r['Organization Code']
            org_name = r['Organization Name']
            state_code = r.get('State Code', '0')
            state_name = r.get('State Name', 'India')

            csv_path = Path(self.csv_filename)
            csv_filename_s = str(csv_path.with_stem('{}_{}'.format(csv_path.stem, org_code)))
            downloader = DirectoryDownloader(name='{}_{}'.format(self.name, org_code),
                                             desc='{} for organization {}({}) of {}({})'\
                                                  .format(self.desc, org_name, org_code, state_name, state_code),
                                             csv_filename=csv_filename_s,
                                             params=self.params,
                                             ctx=self.ctx,
                                             post_data_extra=self.post_data_extra | {
                                                 'entityCodes': ['35', state_code, org_code]
                                             })
            downloader_items.append(DownloaderItem(downloader=downloader, record=r))
        self.downloader_items = downloader_items


class AdminDeptWiseDirectoryDownloader(MultiDownloader, DirectoryDownloader):
    def __init__(self, depends_on='', **kwargs):
        if 'deps' not in kwargs:
            kwargs['deps'] = []

        if depends_on != '' and depends_on not in kwargs['deps']:
            kwargs['deps'].append(depends_on)
        super().__init__(**kwargs)
        self.depends_on = depends_on
        self.post_data_extra = kwargs.get('post_data_extra', {})

    def populate_downloaders(self):
        if self.downloader_items is not None:
            return
        downloader_items = []
        for r in BaseDownloader.records_from_downloader(self.depends_on):
            admin_dept_code = r['adminUnitCode']
            admin_dept_name = r['adminLevelNameEng']
            state_code = r.get('State Code', '0')
            state_name = r.get('State Name', 'India')

            to_date = datetime.today() - timedelta(1)
            #created_on = datetime.strptime(r['createdon'], '%Y-%m-%d %H:%M:%S') 
            #from_date = created_on - timedelta(1)
            from_date = to_date - timedelta(10000)

            from_str = from_date.strftime('%d-%m-%Y')
            to_str = to_date.strftime('%d-%m-%Y')

            csv_path = Path(self.csv_filename)
            csv_filename_s = str(csv_path.with_stem('{}_{}'.format(csv_path.stem, admin_dept_code)))
            downloader = DirectoryDownloader(name='{}_{}'.format(self.name, admin_dept_code),
                                             desc='{} for admin dept {}({}) of {}({})'\
                                                  .format(self.desc, admin_dept_name, admin_dept_code,
                                                          state_name, state_code),
                                             csv_filename=csv_filename_s,
                                             params=self.params,
                                             ctx=self.ctx,
                                             transform=self.transform,
                                             post_data_extra=self.post_data_extra | {
                                                 'entityCodes': ['35', state_code, '', admin_dept_code],
                                                 'lbl': 'FOOBAR',
                                                 'fromDate2': from_str,
                                                 'toDate2': to_str,
                                             })
            downloader_items.append(DownloaderItem(downloader=downloader, record=r))
        self.downloader_items = downloader_items


class ConstituencyWiseDirectoryDownloader(MultiDownloader, DirectoryDownloader):
    def __init__(self, **kwargs):
        if 'enrichers' not in kwargs:
            kwargs['enrichers'] = { 'State Code': 'State Code',
                                    'Parliament Constituency Code': 'Parliament Constituency Code' }
        if 'deps' not in kwargs:
            kwargs['deps'] = []
        if 'CONSTITUENCIES_PARLIAMENT' not in kwargs['deps']:
            kwargs['deps'].append('CONSTITUENCIES_PARLIAMENT')
        super().__init__(**kwargs)
        self.post_data_extra = kwargs.get('post_data_extra', {})


    def populate_downloaders(self):
        if self.downloader_items is not None:
            return
        downloader_items = []
        for r in BaseDownloader.records_from_downloader('CONSTITUENCIES_PARLIAMENT'):
            state_code = r['State Code']
            state_name = r['State Name']
            const_name = r['Parliament Constituency Name']
            const_code = r['Parliament Constituency Code']


            csv_path = Path(self.csv_filename)
            csv_filename_s = str(csv_path.with_stem('{}_{}_{}'.format(csv_path.stem, state_code, const_code)))
            downloader = DirectoryDownloader(name='{}_{}_{}'.format(self.name, state_code, const_code),
                                             desc='{} for constituency {}({}) of state {}({})'.format(self.desc, const_name, const_code, state_name, state_code),
                                             csv_filename=csv_filename_s,
                                             params=self.params,
                                             ctx=self.ctx,
                                             post_data_extra=self.post_data_extra | {
                                                 'stateName': state_name,
                                                 'entityCodes': [state_code, const_code],
                                             })
            downloader_items.append(DownloaderItem(downloader=downloader, record=r))
        self.downloader_items = downloader_items
 

def get_all_directory_downloaders(params, ctx):
    downloaders = []
    downloaders.append(DirectoryDownloader(name='STATES',
                                           desc='list of all states',
                                           dropdown='STATE --> All States of India',
                                           csv_filename='states.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'allStateofIndia',
                                               'downloadType': 'odt' # because the header came out unbroken in odt
                                           }))
    downloaders.append(DirectoryDownloader(name='DISTRICTS',
                                           desc='list of all districts',
                                           dropdown='DISTRICT --> All Districts of India',
                                           csv_filename='districts.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'allDistrictofIndia',
                                               'downloadType': 'odt', # because the header came out unbroken in odt
                                           }))
    downloaders.append(DirectoryDownloader(name='SUB_DISTRICTS', 
                                           desc='list of all subdistricts',
                                           dropdown='SUB-DISTRICT --> All Sub-Districts of India',
                                           csv_filename='subdistricts.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'allSubDistrictofIndia',
                                           }))
    downloaders.append(DirectoryDownloader(name='BLOCKS',
                                           desc='list of all blocks',
                                           dropdown='Block --> All Blocks of India',
                                           csv_filename='blocks.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'allBlockofIndia',
                                               'downloadType': 'odt' # because the header came out unbroken in odt as opposed xls
                                           }))
    # Too big.. had to break to statewise downloads
    #downloaders.append(DirectoryDownloader(name='VILLAGES',
    #                                       desc='list of all villages',
    #                                       dropdown='VILLAGE --> All Villages of India',
    #                                       csv_filename='villages.csv',
    #                                       params=params,
    #                                       ctx=ctx,
    #                                       post_data_extra={
    #                                           'rptFileName': 'allVillagesofIndia',
    #                                       }))
    #downloaders.append(DirectoryDownloader(name='BLOCK_VILLAGES',
    #                                       desc='list of all village to block mappings',
    #                                       dropdown='Block --> Subdistrict, Block,Village and Gps Mapping',
    #                                       csv_filename='villages_by_blocks.csv',
    #                                       params=params,
    #                                       ctx=ctx,
    #                                       post_data_extra={
    #                                           'rptFileName': 'subdistrictVillageBlockGpsMapping',
    #                                       }))
    #downloaders.append(DirectoryDownloader(name='PRI_LOCAL_BODIES',
    #                                       desc='list of all PRI(Panchayati Raj India) local bodies',
    #                                       dropdown='Local body --> All PRI Local Bodies of India',
    #                                       csv_filename='pri_local_bodies.csv',
    #                                       params=params,
    #                                       ctx=ctx,
    #                                       post_data_extra={
    #                                           'rptFileName': 'priLocalBodyIndia',
    #                                           'downloadType': 'odt' # because the header came out unbroken in odt as opposed xls
    #                                       }))
    downloaders.append(DirectoryDownloader(name='TRADITIONAL_LOCAL_BODIES',
                                           desc='list of all Traditional local bodies',
                                           dropdown='Local body --> All Traditional Local Bodies of India',
                                           csv_filename='traditional_local_bodies.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'allTraditionalLBofInida',
                                               'downloadType': 'odt' # because the header came out unbroken in odt as opposed xls
                                           }))
    downloaders.append(DirectoryDownloader(name='URBAN_LOCAL_BODIES',
                                           desc='list of all urban local bodies',
                                           dropdown='Local body --> All Urban Local Bodies of India',
                                           csv_filename='urban_local_bodies.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'urbanLocalBodyIndia',
                                               'downloadType': 'odt' # because the header came out unbroken in odt as opposed xls
                                           }))
    downloaders.append(DirectoryDownloader(name='URBAN_LOCAL_BODIES_COVERAGE',
                                           desc='list of all urban local bodies with coverage',
                                           dropdown='Local body --> Urban Localbodies with Coverage',
                                           csv_filename='statewise_ulbs_coverage.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'statewise_ulbs_coverage',
                                               'downloadType': 'odt' # because the header came out unbroken in odt as opposed xls
                                           }))
    downloaders.append(DirectoryDownloader(name='CONSTITUENCIES_PARLIAMENT',
                                           desc='list of all parliament constituencies',
                                           dropdown='Parliament/Assembly Constituency --> Parliament Constituency or Assembly Constituency of a State/India --> All State --> Parliament Constituency',
                                           csv_filename='parliament_constituencies.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'assembly_parliament_constituency',
                                               'stateName': 'India',
                                               'entityCodes': ['35', '0'],
                                               'assemblyParliamentConstituency': '#PC'
                                           }))
    downloaders.append(DirectoryDownloader(name='CONSTITUENCIES_ASSEMBLY',
                                           desc='list of all assembly constituencies',
                                           dropdown='Parliament/Assembly Constituency --> Parliament Constituency or Assembly Constituency of a State/India --> All State --> Assembly Constituency',
                                           csv_filename='assembly_constituencies.csv',
                                           params=params,
                                           ctx=ctx,
                                           post_data_extra={
                                               'rptFileName': 'assembly_parliament_constituency',
                                               'stateName': 'India',
                                               'entityCodes': ['35', '0'],
                                               'assemblyParliamentConstituency': '#AC'
                                           }))
    downloaders.append(DirectoryDownloader(name='CENTRAL_ORG_DETAILS',
                                           desc='list of all central organization details',
                                           dropdown='Department/Organization --> Departments/Organization Details --> Central',
                                           csv_filename='central_orgs.csv',
                                           params=params,
                                           ctx=ctx,
                                           transform=lambda x: False if x['Organization Code'] == '' else x,
                                           post_data_extra={
                                               'rptFileName': 'parentWiseOrganizationDepartmentDetails',
                                               'state': '0',
                                               'entityCodes': ['35', '0', '0'],
                                           }))

    downloaders.append(StateWiseDirectoryDownloader(name='VILLAGES',
                                                    desc='list of all villages',
                                                    dropdown='VILLAGE --> All Villages of a State',
                                                    csv_filename='villages.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'villageofSpecificState@state',
                                                        'downloadType': 'odt' # because the header came out unbroken in odt as opposed xls
                                                    },
                                                    enrichers={
                                                        'State Code': 'State Code',
                                                        'State Name (In English)': 'State Name(In English)'
                                                    }))
    downloaders.append(StateWiseDirectoryDownloader(name='BLOCK_VILLAGES',
                                                    desc='list of all village to block mappings',
                                                    dropdown='Block --> Subdistrict, Block,Village and Gps Mapping',
                                                    csv_filename='villages_by_blocks.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'subdistrictVillageBlockGpsMapping',
                                                    },
                                                    enrichers={}))
    downloaders.append(StateWiseDirectoryDownloader(name='PRI_LOCAL_BODIES',
                                                    desc='list of all PRI(Panchayati Raj India) local bodies',
                                                    dropdown='Local body --> PRI Local Body of a State',
                                                    csv_filename='pri_local_bodies.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'priLbSpecificState@state',
                                                        'state': 'on',
                                                        'downloadType': 'odt' # because the header came out unbroken in odt as opposed xls
                                                    }))
    # missing in lgd drop downs and data lacking compared to CONSTITUENCIES_MAPPINGS_PRI and CONSTITUENCIES_MAPPINGS_URBAN
    #downloaders.append(StateWiseDirectoryDownloader(name='CONSTITUENCIES_MAPPINGS',
    #                                                desc='list of all constituencies with local body coverage',
    #                                                csv_filename='constituencies_mapping.csv',
    #                                                params=params,
    #                                                ctx=ctx,
    #                                                post_data_extra={
    #                                                    'rptFileName': 'parlimentConstituencyAndAssemblyConstituency@state'
    #                                                },
    #                                                enrichers={
    #                                                    'State Code': 'State Code'
    #                                                }))
    downloaders.append(StateWiseDirectoryDownloader(name='CONSTITUENCIES_MAPPINGS_PRI',
                                                    desc='list of all constituencies with PRI local body coverage',
                                                    dropdown='Parliament/Assembly Constituency --> State Wise Parliament Constituency and Assembly Constituency along with coverage details PRI',
                                                    csv_filename='constituencies_mapping_pri.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'parlimentConstituencyAndAssemblyConstituencyPRI@state'
                                                    },
                                                    enrichers={
                                                        'State Code': 'State Code'
                                                    }))
    downloaders.append(StateWiseDirectoryDownloader(name='CONSTITUENCIES_MAPPINGS_URBAN',
                                                    desc='list of all constituencies with Urban local body coverage',
                                                    dropdown='Parliament/Assembly Constituency --> State Wise Parliament Constituency and Assembly Constituency along with coverage details Urban',
                                                    csv_filename='constituencies_mapping_urban.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'parlimentConstituencyAndAssemblyConstituencyUrban@state'
                                                    },
                                                    enrichers={
                                                        'State Code': 'State Code'
                                                    }))
    downloaders.append(StateWiseDirectoryDownloader(name='PANCHAYAT_MAPPINGS',
                                                    desc='list of all panchayat mappings',
                                                    dropdown='Gram Panchayat Mapping to village --> Gram Panchayat Mapping to village',
                                                    csv_filename='gp_mapping.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'LocalbodyMappingtoCensusLandregionCode@state',
                                                        'downloadType': 'odt'
                                                    }))
    downloaders.append(StateWiseDirectoryDownloader(name='PRI_LOCAL_BODY_WARDS',
                                                    desc='list of all PRI Local body wards',
                                                    dropdown='Local body --> Wards of PRI Local Bodies',
                                                    csv_filename='pri_local_body_wards.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'priWards@state'
                                                    }))
    downloaders.append(StateWiseDirectoryDownloader(name='URBAN_LOCAL_BODY_WARDS',
                                                    desc='list of all Urban Local body wards',
                                                    dropdown='Local body --> Wards of Urban Local Bodies',
                                                    csv_filename='urban_local_body_wards.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    post_data_extra={
                                                        'rptFileName': 'uLBWardforState@state'
                                                    }))
    downloaders.append(StateWiseDirectoryDownloader(name='CONSTITUENCY_COVERAGE',
                                                    desc='list of all assembly/parliament constituencies and their coverage',
                                                    dropdown='Parliament/Assembly Constituency --> Constituency Coverage Details',
                                                    csv_filename='constituency_coverage.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    transform=lambda x: False if x['Parliament Constituency Code'] == '' else x,
                                                    post_data_extra={
                                                        'rptFileName': 'constituencyReport@state'
                                                    }))
 
    downloaders.append(StateWiseDirectoryDownloader(name='STATE_ORG_DETAILS',
                                                    desc='list of all state level organizations',
                                                    dropdown='Department/Organization --> Departments/Organization Details --> State',
                                                    csv_filename='state_orgs.csv',
                                                    params=params,
                                                    ctx=ctx,
                                                    transform=lambda x: False if x['Organization Code'] == '' else x,
                                                    post_data_extra={
                                                        'rptFileName': 'parentWiseOrganizationDepartmentDetails',
                                                        'state': 'on'
                                                    }))



    downloaders.append(ConstituencyWiseDirectoryDownloader(name='PARLIAMENT_CONSTITUENCIES_LOCAL_BODY_MAPPINGS',
                                                           desc='list of all parliament constituencies with local body coverage',
                                                           dropdown='Parliament/Assembly Constituency --> Parliament Wise Local Body Mapping',
                                                           csv_filename='parliament_constituencies_lb_mapping.csv',
                                                           params=params,
                                                           ctx=ctx,
                                                           post_data_extra={
                                                               'rptFileName': 'parliamentConstituency@state#parliament'
                                                           }))



    downloaders.append(OrgWiseDirectoryDownloader(name='STATE_ORG_UNITS',
                                                  desc='list of all state level organization units',
                                                  dropdown='Department/Organization --> Organization Units of a Department/Organization --> State',
                                                  csv_filename='state_org_units.csv',
                                                  depends_on='STATE_ORG_DETAILS',
                                                  params=params,
                                                  ctx=ctx,
                                                  post_data_extra={
                                                        'rptFileName': 'orgUnitBasedOnOrgCode',
                                                        'downloadType': 'odt',
                                                        'state': 'on'
                                                  },
                                                  enrichers={
                                                      'Base Organization Name': 'Organization Name',
                                                      'Base Organization Code': 'Organization Code',
                                                      'State Name': 'State Name',
                                                      'State Code': 'State Code'
                                                  }))
    downloaders.append(OrgWiseDirectoryDownloader(name='CENTRAL_ORG_UNITS',
                                                  desc='list of all central organization units',
                                                  dropdown='Department/Organization --> Organization Units of a Department/Organization --> Central',
                                                  csv_filename='central_org_units.csv',
                                                  depends_on='CENTRAL_ORG_DETAILS',
                                                  params=params,
                                                  ctx=ctx,
                                                  post_data_extra={
                                                        'rptFileName': 'orgUnitBasedOnOrgCode',
                                                        'downloadType': 'odt',
                                                        'state': '0'
                                                  },
                                                  enrichers={
                                                      'Base Organization Name': 'Organization Name',
                                                      'Base Organization Code': 'Organization Code',
                                                  }))
    downloaders.append(OrgWiseDirectoryDownloader(name='STATE_ORG_DESIGNATIONS',
                                                  desc='list of all state level organization designations',
                                                  dropdown='Department/Organization --> Designations of a Department/Organization --> State',
                                                  csv_filename='state_org_designations.csv',
                                                  depends_on='STATE_ORG_DETAILS',
                                                  params=params,
                                                  ctx=ctx,
                                                  post_data_extra={
                                                        'rptFileName': 'designationBasedOnOrgCode',
                                                        'state': 'on'
                                                  },
                                                  enrichers={
                                                      'Base Organization Name': 'Organization Name',
                                                      'Base Organization Code': 'Organization Code',
                                                      'State Name': 'State Name',
                                                      'State Code': 'State Code'
                                                  }))
    downloaders.append(OrgWiseDirectoryDownloader(name='CENTRAL_ORG_DESIGNATIONS',
                                                  desc='list of all central organization designations',
                                                  dropdown='Department/Organization --> Designations of a Department/Organization --> Central',
                                                  csv_filename='central_org_designations.csv',
                                                  depends_on='CENTRAL_ORG_DETAILS',
                                                  params=params,
                                                  ctx=ctx,
                                                  post_data_extra={
                                                        'rptFileName': 'designationBasedOnOrgCode',
                                                        'state': '0'
                                                  },
                                                  enrichers={
                                                      'Base Organization Name': 'Organization Name',
                                                      'Base Organization Code': 'Organization Code',
                                                  }))


    downloaders.append(AdminDeptWiseDirectoryDownloader(name='CENTRAL_ADMIN_DEPT_UNITS',
                                                        desc='list of all central adminstrative department units',
                                                        dropdown='Department/Organization --> Administrative Unit Level Wise Administrative Unit Entity --> Central',
                                                        csv_filename='central_admin_dept_units.csv',
                                                        depends_on='CENTRAL_ADMIN_DEPTS',
                                                        params=params,
                                                        ctx=ctx,
                                                        transform=lambda x: False if x['Admin Unit Entity Code'] == '' else x,
                                                        post_data_extra={
                                                              'rptFileName': 'adminUnitLevelAdminUnitEntity',
                                                              'state': '0',
                                                        },
                                                        enrichers={
                                                            'Admin Department Name': 'adminLevelNameEng',
                                                            'Admin Department Code': 'adminUnitCode',
                                                        }))
    downloaders.append(AdminDeptWiseDirectoryDownloader(name='STATE_ADMIN_DEPT_UNITS',
                                                        desc='list of all state adminstrative department units',
                                                        dropdown='Department/Organization --> Administrative Unit Level Wise Administrative Unit Entity --> State',
                                                        csv_filename='state_admin_dept_units.csv',
                                                        depends_on='STATE_ADMIN_DEPTS',
                                                        params=params,
                                                        ctx=ctx,
                                                        transform=lambda x: False if x['Admin Unit Entity Code'] == '' else x,
                                                        post_data_extra={
                                                              'rptFileName': 'adminUnitLevelAdminUnitEntity',
                                                              'state': 'on'
                                                        },
                                                        enrichers={
                                                            'Admin Department Name': 'adminLevelNameEng',
                                                            'Admin Department Code': 'adminUnitCode',
                                                            'State Name': 'State Name',
                                                            'State Code': 'State Code'
                                                        }))

    return downloaders

