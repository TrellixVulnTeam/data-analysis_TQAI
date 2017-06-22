from __future__ import print_function

import StringIO
import collections
import gzip
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections import Mapping, Set, Sequence

import hashtools
import jsonify
import printhook
from bcolors import render as render
from caches import cache_core
from printhook import decorate_method_log


global_log_enabled=True
global_fancy_output=False
#global_suppress_output=False
global_all_output=True
#global_readonly_caches=False
global_output_levels=('top')

from  printhook import log,debug_print

from dataanalysis.analysisfactory import AnalysisFactory

Cache = cache_core.CacheNoIndex()
TransientCacheInstance = cache_core.TransientCache()


# TODO:

# approprate logging
# reporting classes
# optional input
# cache migration
# track all exceptions!!!
# hashe to picture
# deleting files: cleanup after analysis
# cache module not irods but git

# delegation simple, in scripts

# data intergity: prevent corruption during copying to/from hashe

# transient cache no work as expected? call same analysis?

# cache-only analysis
# cache migration
# hashe operations: hashe spearation

# need more flexible system to interpret object:
#    interpret aliases

#  exceptions handle better
#  output hash in never-cached objects
#  timestamps
#  more nested caches!

# there are several ways to construct new analysis
#  - inherit class from dataanalysis. identified by class name
#  - create an object with arguments. by class name and arguments (_da_attributes)

# translation of subgraphs: rewrite rules

# add advanced verification while setting arguments: do not allow objects of DA (or treat them?) and big data

# an option for "testing" state object, forces all requesters to recompute



#

#AnalysisDict={}


# dual python 2/3 compatability, inspired by the "six" library
string_types = (str, unicode) if str is bytes else (str, bytes)
iteritems = lambda mapping: getattr(mapping, 'iteritems', mapping.items)()

def get_cwd():
    tf=tempfile.NamedTemporaryFile()
    ppw=subprocess.Popen(["pwd"],stdout=tf)
    ppw.wait()

    try:
        ppw.terminate()
    except OSError:
        pass
    tf.seek(0)
    owd=tf.read()[:-1]
    log("old pwd gives me",owd)
    tf.close()
    del tf
    return owd


def athostdir(f):
    def wrapped(self,*a,**aa):
        owd=get_cwd()
        try:
            if not os.path.exists(self.hostdir):
                os.makedirs(self.hostdir)
            os.chdir(self.hostdir)
            r=f(self,*a,**aa)
        except Exception as e:
            log("exception in wrapped:",e)
            os.chdir(owd)
            raise
        os.chdir(owd)
        return r
    return wrapped

class DataHandle:
    trivial = True
    pass


class NoAnalysis:
    pass

def isdataanalysis(obj,alsofile=False):
    if isinstance(obj,DataFile) and not alsofile:
        return False
    if isinstance(obj,DataAnalysis):
        return True
    if isinstance(obj,type) and issubclass(obj,DataAnalysis):
        return True
    return False

def objwalk(obj, path=(), memo=None, sel=lambda x:True):
    #log("walking in",obj,path)
    if memo is None:
        memo = set()
    iterator = None
    if isinstance(obj, Mapping):
        iterator = iteritems
    elif isinstance(obj, (Sequence, Set)) and not isinstance(obj, string_types):
        iterator = enumerate
    if iterator:
        #log("walking interate")
        if id(obj) not in memo:
            memo.add(id(obj))
            for path_component, value in iterator(obj):
         #       log("walking",path,path_component,value)
                for result in objwalk(value, path + (path_component,), memo, sel):
                    yield result
            memo.remove(id(obj))
    else:
        #log("walk end",path,obj)
        if sel(obj):
         #   log("walk selected",path,obj)
            yield obj

#/objwalk

def update_dict(a,b):
    return dict(a.items()+b.items())

class AnalysisException(Exception):
    pass


class decorate_all_methods(type):
    def __new__(cls, name, bases, local):
        # also store in the dict

        # decorate
        if printhook.global_fancy_output:
            for attr in local:
                value = local[attr]
                if callable(value) and not isinstance(value,type):
                    local[attr] = decorate_method_log(value)
        else:
            if printhook.global_catch_main_output and 'main' in local:
                debug_print("decorating only main in "+repr(cls)+"; "+repr(name))
                local['main'] = decorate_method_log(local['main'])

        c=type.__new__(cls, name, bases, local)

        if not c.trivial:
            log("declaring analysis class",name,)
            log("   constructing object...")
            o=c(update=True)
            log("   registered",o)

        return c

class DataAnalysis(object):
    __metaclass__ = decorate_all_methods

    infactory=True
    trivial=False # those that do not need to be computed

    factory=AnalysisFactory
    cache=Cache

    cached=False

    abstract=False

    run_for_hashe=False
    mutating=False
    copy_cached_input=True
    datafile_restore_mode=None

    incomplete=False

    only_verify_cache_record=False

    schema_hidden=False

    test_files=True

    assumptions=[]

    essential_deep_inputs=()

    default_log_level=""

    explicit_output=None

    min_timespent_tocache=5.
    min_timespent_tocache_hard=0.5
    max_timespent_tocache=5.
    allow_timespent_adjustment=False
    hard_timespent_checks=False

    allow_alias=False

    virtual=True

    noanalysis=False

    rename_output_unique=True

    force_complete_input=True

    def is_virtual(self):
        #if self.run_for_hashe: return False
        return self.virtual

    _da_restored=None
    _da_locally_complete=None
    _da_main_delegated=None
    _da_main_log_content=""
    _da_delegated_input=None
    _da_ignore_output_objects=False

    _da_main_log_content=""

    write_caches=[cache_core.Cache]
    read_caches=[cache_core.Cache]

    #def get_dynamic_input(self):
     #   if hasattr(self,'input_dynamic'):
      #      return self.input_dynamic
      #  return []

    _da_settings=None

    def str(self):
        if hasattr(self,'handle'): return self.handle
        return repr(self)

    def get_factory_name(self):
        if hasattr(self, 'name'):
            name = self.name
        else:
            name = self.__class__.__name__

        return name

    def __new__(self,*a,**args): # no need to split this in new and factory, all togather
        self=object.__new__(self)

        # otherwise construct object, test if already there

        self._da_attributes=dict([(a,b) for a,b in args.items() if a!="assume" and not a.startswith("input") and a!="update" and a!="dynamic" and not a.startswith("use_") and not a.startswith("set_")]) # exclude registered


        update=False
        #update=True
        if 'update' in args:
            log("update in the args:",update)
            update=args['update']

        for a,b in args.items():
            if a.startswith("input"):
                log("input in the constructor:",a,b)
                setattr(self,a,b)
                log("explicite input require non-virtual") # differently!
                self.virtual=False
                self._da_virtual_reason='explicit input:'+repr(a)+" = "+repr(b)

            if a.startswith("use"):
                log("use in the constructor:",a,b)
                setattr(self,a.replace("use_",""),b)
                log("explicite use require non-virtual") # differently!
                self.virtual=False
                self._da_virtual_reason='explicit use:'+repr(a)+" = "+repr(b)

            if a.startswith("set"):
                log("set in the constructor:",a,b)
                setting_name=a.replace("set_","")
                setattr(self,setting_name,b)
                if self._da_settings is None:
                    self._da_settings=[]
                self._da_settings.append(setting_name)
                log('settings:',self,self._da_settings,level='top')
                #log("explicite use require non-virtual") # differently!
                #self.virtual=False
                #self._da_virtual_reason='explicit use:'+repr(a)+" = "+repr(b)

        name=self.get_signature()
        log("requested object",name,"attributes",self._da_attributes)

        if 'dynamic' in args and not args['dynamic']:
            log("not dynamic object:",self,level='dynamic')
            r=self
        else:
            log("dynamic object, from",self,level='dynamic')
            r=AnalysisFactory.get(self,update=update)
            log("dynamic object, to",r,level='dynamic')

        if 'assume' in args and args['assume']!=[]:
            log("replacing with a copy: < ",r,level='dynamic')
            r=r.__class__(dynamic=False) # replace with a copy
            log("replacing with a copy: > ",r,level='dynamic')
            r.assumptions=args['assume']
            if not isinstance(r.assumptions,list): # iteratable?
                r.assumptions=[r.assumptions]
            log("assuming with a copy: > ",r,level='dynamic')
            log("requested assumptions:",self.assumptions)
            log("explicite assumptions require non-virtual") # differently!
            #self.virtual=False
            r._da_virtual_reason='assumptions:'+repr(self.assumptions)

        return r

    def promote(self):
        log("promoting to the factory",self)
        return AnalysisFactory.put(self)

    def verify_content(self):
        return True

#   implements:
#       caching
#
#       dependencies
#
#   input hashes + version => output hash

    #input= no inpuit!

    version="v0"

    def main(self):
        pass

    def get_stamp(self):
        return {'host':socket.gethostname(),
                  'time':time.time(),
                  'htime':time.ctime(),
                  'proc':sys.argv,
                  'pid':os.getpid()}


    def interpret_item(self,item):
        return AnalysisFactory.get(item,update=False)

    def import_data(self,data):
        log("updating analysis with data")
        for a,b in data.items():
            setattr(self,a,b)

    def jsonify(self,embed_datafiles=False,verify_jsonifiable=False):
        return self.export_data(embed_datafiles,verify_jsonifiable)

    def export_data(self,embed_datafiles=False,verify_jsonifiable=False):
        empty_copy=self.__class__
        log("my class is",self.__class__)
        updates=set(self.__dict__.keys())-set(empty_copy.__dict__.keys())
        log("new keys:",updates)
        # or state of old keys??

        if self.explicit_output is not None:
            log("explicit output requested",self.explicit_output)
            r=dict([[a,getattr(self,a)] for a in self.explicit_output if hasattr(self,a)])
        else:
            r=dict([[a,getattr(self,a)] for a in updates if not a.startswith("_") and not a.startswith("set_") and not a.startswith("use_") and not a.startswith("input") and not a.startswith('assumptions')])

        if verify_jsonifiable:
            res=[]
            for a,b in r.items():
                res.append([a,jsonify(b)])
            r=dict(res)

        log("resulting output:",r)
        return r

    def import_data(self,c):
        # todo: check that the object is fresh
        for k, i in c.items():
            log("restoring", k, i)
            setattr(self, k, i)

    def serialize(self):
        return self.get_factory_name(),self.export_data()

    # the difference between signature and version is that version can be avoided in definition and substituted later
    # it can be done differently
    # e.g. versions can be completely avoided


    def get_formatted_attributes(self):
        if hasattr(self,'_da_attributes'): #not like that
            return "_".join(["%s.%s"%(str(a),repr(b).replace("'","")) for a,b in self._da_attributes.items()])
        else:
            return ""

    def get_version(self):
        ss="_".join(["%s:%s"%(a,repr(getattr(self,a))) for a in self._da_settings]) if self._da_settings is not None else ""
        v=self.get_signature()+"."+self.version+("."+ss if ss!="" else "")
        #if hasattr(self,'timestamp'):
        #    v+=".at_"+str(self.timestamp)
        return v

    def get_signature(self):
        a=self.get_formatted_attributes()
        if a!="": a="."+a

        state=self.get_state()
        if state is not None:
            a=a+"."+state


        return self.get_factory_name()+a

    def get_state(self):
        if not hasattr(self,'_da_state'):
            self._da_state=self.compute_state()
        return self._da_state

    def compute_state(self):
        return None

    def process_output_files(self,hashe):
        """
        rename output files to unique filenames
        """

        content=self.export_data()
        if isinstance(content,dict):
            for a,b in content.items():
                if isinstance(b,DataFile):
                    dest_unique=b.path+"."+self.cache.hashe2signature(hashe) # will it always?
                    b._da_unique_local_path=dest_unique
                    shutil.copyfile(b.path,dest_unique)
                    log("post-processing DataFile",b,"as",b._da_unique_local_path,log='datafile')

    def store_cache(self,fih):
        """
    store output with
        """

        log(render("{MAGENTA}storing in cache{/}"))
        log("hashe:",fih)

     #   c=MemCacheLocal.store(fih,self.export_data())
        #log(render("{MAGENTA}this is non-cached analysis, reduced caching: only transient{/}"))
        TransientCacheInstance.store(fih,self)
        self.cache.store(fih,self)
        #c=MemCacheLocal.store(oh,self.export_data())

    def post_restore(self):
        pass

    def retrieve_cache(self,fih,rc=None):
        log("requested cache for",fih)

        if self._da_locally_complete is not None:
            log("this object has been already restored and complete",self)
            if self._da_locally_complete == fih:
                log("this object has been completed with the neccessary hash: no need to recover state",self)
                if not hasattr(self,'_da_recovered_restore_config'):
                    log("the object has not record of restore config",level='top')
                    return True
                if rc==self._da_recovered_restore_config:
                    log("the object was recovered with the same restore config:",rc,self._da_recovered_restore_config,level='top')
                    return True
                log("the object was recovered with a different restore config:",self._da_recovered_restore_config,'became',rc,level='top')
            else:
                log("state of this object isincompatible with the requested!")
                log(" was: ",self._da_locally_complete)
                log(" now: ",fih)
                #raise Exception("hm, changing analysis dictionary?")
                log("hm, changing analysis dictionary?","{log:thoughts}")

                if self.run_for_hashe:
                    log("object is run_for_hashe, this is probably the reason")

                return None

        if rc is None:
            rc={}

        r=TransientCacheInstance.restore(fih,self,rc)

        if r and r is not None:
            log("restored from transient: this object will be considered restored and complete: will not do again",self)
            self._da_locally_complete=True # info save
            return r

        if not self.cached:
            log(render("{MAGENTA}not cached restore only from transient{/}"))
            return None # only transient!
        # discover through different caches
        #c=MemCacheLocal.find(fih)

        r=self.cache.restore(fih,self,rc)

        if r and r is not None:
            log("this object will be considered restored and complete: will not do again",self)
            self._da_locally_complete=fih # info save
            log("locally complete:",fih)
            self.post_restore()
            if self.rename_output_unique and rc['datafile_restore_mode']=="copy":
                self.process_output_files(fih)
            else:
                log("disabled self.rename_output_unique",level='cache')
            return r
        return r # twice


    def plot_schema(self,fn="schema.png"):
        self.get_schema().write_png(fn)

    def get_schema(self,graph=None):
        import pydot

        graph = pydot.Dot(graph_type='digraph')

        def make_schema(i1,i2):

            if not isinstance(i2,DataAnalysis):
                return

            if i2.schema_hidden:
                return

            node = pydot.Node(repr(i2), style="filled", fillcolor="green")
            node = pydot.Node(repr(i1), style="filled", fillcolor="green")

            edge = pydot.Edge(repr(i2), repr(i1))
            graph.add_edge(edge)

        self.process_input(obj=None,process_function=make_schema,explicit_input_required=False)

        # do it all from hash, no need to construct again
        return graph

    def get(self,**aa):
        if 'saveonly' in aa and aa['saveonly'] is not None:
            import errno
            import shutil
            import tempfile

            aax=dict(aa.items()+[['saveonly',None]])

            try:
                tmp_dir = tempfile.mkdtemp()  # create dir
                print("tempdir:",tmp_dir)
                olddir=os.getcwd()
                os.chdir(tmp_dir)
                self.get(**aax)

                for fn in aa['saveonly']:
                    shutil.copyfile(tmp_dir+"/"+fn,olddir+"/"+fn)

            finally:
                try:
                    shutil.rmtree(tmp_dir)  # delete directory
                except OSError as exc:
                    if exc.errno != errno.ENOENT:  # ENOENT - no such file or directory
                        raise  # re-raise exception

        return self.process(output_required=True,**aa)[1]

    def load(self,**aa):
        fih=self._da_locally_complete
        if fih is None:
            fih=self.process(output_required=False,**aa)[0]

        print("restoring as",fih)
        self.retrieve_cache(fih)
        return self.get(**aa)

    def stamp(self,comment,**aa):
        self.comment=comment
        import time
        self.timestamp=time.time()

        fih=self._da_locally_complete
        if fih is None:
            fih=self.process(output_required=False,**aa)[0]

        print("storing as",fih)
        return self.store_cache(fih)

    def process_checkin_assumptions(self):
        if self.assumptions!=[]:
            log("cache assumptions:",AnalysisFactory.cache_assumptions)
            log("assumptions:",self.assumptions)
            log("non-trivial assumptions require copy of the analysis tree")
            AnalysisFactory.WhatIfCopy("requested by "+repr(self),self.assumptions)
            for a in self.assumptions:
                a.promote()
        else:
            log("no special assumptions")

    def process_checkout_assumptions(self):
        log("assumptions checkout")
        if self.assumptions!=[]:
            AnalysisFactory.WhatIfNot()

    def process_restore_rules(self,restore_rules,extra):
        log("suggested restore rules:",restore_rules)
        restore_rules_default=dict(
                    output_required=False,
                    substitute_output_required=False,
                    explicit_input_required=False,
                    restore_complete=False,
                    restore_noncached=False,
                    run_if_haveto=True,
                    input_runs_if_haveto=False,
                    can_delegate=False,
                    can_delegate_input=False,
                    run_if_can_not_delegate=True,
                    force_complete=True,
                    force_complete_input=True)
        restore_rules=dict(restore_rules_default.items()+(restore_rules.items() if restore_rules is not None else []))
        # to simplify input
        for k in extra.keys():
            if k in restore_rules:
                restore_rules[k]=extra[k]

        # always run to process
        restore_rules['substitute_output_required']=restore_rules['output_required']
        if self.run_for_hashe:
            log(render("{BLUE}this analysis has to run for hashe! this will be treated later, requiring output{/}"))
            log(render("{BLUE}original object output required?{/}"+str(restore_rules['output_required'])))
            restore_rules['output_required']=True
            restore_rules['explicit_input_required']=True
            restore_rules['input_runs_if_haveto']=True
            restore_rules['run_if_haveto']=True

        #restore_rules['force_complete_input']=self.force_complete_input

        log("will use restore_rules:",restore_rules)
        return restore_rules

    def process_restore_config(self,restore_config):
        rc=restore_config # this is for data restore modes, passed to cache
        if restore_config is None:
            rc={'datafile_restore_mode':'copy'}

        log('restore_config:',rc)
        return rc


    def process_timespent_interpret(self):
        tspent=self.time_spent_in_main
        if tspent<self.min_timespent_tocache and self.cached:
            log(render("{RED}requested to cache fast analysis!{/} {MAGENTA}%.5lg seconds < %.5lg{/}"%(tspent,self.min_timespent_tocache)))
            if self.allow_timespent_adjustment:
                log(render("{MAGENTA}temporarily disabling caching for this analysis{/}"))
                self.cached=False
            else:
                log("being ignorant about it")

            if tspent<self.min_timespent_tocache_hard and self.cached:
                if self.hard_timespent_checks:
                    estr=render("{RED}requested to cache fast analysis, hard limit reached!{/} {MAGENTA}%.5lg seconds < %.5lg{/}"%(tspent,self.min_timespent_tocache_hard))
                    raise Exception(estr)
                else:
                    log("ignoring hard limit on request")

        if tspent>self.max_timespent_tocache and not self.cached:
            log(render("{BLUE}analysis takes a lot of time but not cached, recommendation is to cache!{/}"),"{log:advice}")

    def treat_input_analysis_exceptions(self,analysis_exceptions):
        return False

    def get_exceptions(self):
        if not hasattr(self,'analysis_exceptions'):
            return []
        return self.analysis_exceptions

    def note_analysis_exception(self,ae):
        if not hasattr(self,'analysis_exceptions'):
            self.analysis_exceptions=[]
        self.analysis_exceptions.append((self.get_signature(),ae))

    watched_analysis=False

    def start_main_watchdog(self):
        log("main watchdog")
        self.report_runtime("starting")
        if not self.watched_analysis: return
        # do it?
        self.cache.report_analysis_state(self,"running")


    def stop_main_watchdog(self):
        self.report_runtime("done")
        if not self.watched_analysis: return
        self.cache.report_analysis_state(self,"done")

    def process_run_main(self):
        #self.runtime_update('running')
        if self.abstract:
            raise Exception("attempting to run abstract! :"+repr(self)+" requested by "+(" ".join(self._da_requested_by)))

        dll=self.default_log_level
        self.default_log_level="main"

        log(render("{RED}running main{/}"),'{log:top}')
        t0=time.time()
        main_log=StringIO.StringIO()
        main_logstream= printhook.LogStream(main_log, lambda x:True, name="main stream")
        main_logstream.register()
        main_logstream_file= printhook.LogStream("main.log", lambda x:True, name="main stream file")
        main_logstream_file.register()
        log("starting main log stream",main_log,main_logstream,level='logstreams')

        self.start_main_watchdog()

        try:
            mr=self.main() # main!
        except AnalysisException as ae:
            self.note_analysis_exception(ae)
            mr=None
        except Exception as e:
            #os.system("ls -ltor")
            self.stop_main_watchdog()
            os.system("echo current dir;pwd")

            try:
                self.cache.report_exception(self,e)
                self.report_runtime("failed "+repr(e))
            except Exception:
                print("unable to report exception!")

            raise
        self.stop_main_watchdog()

        main_logstream.forget()
        main_logstream_file.forget()
        self._da_main_log_content=main_log.getvalue()
        main_log.close()
        log("main log stream collected",len(self._da_main_log_content),level="logstreams")
        log("closing main log stream",main_log,main_logstream,level="logstreams")

        tspent=time.time()-t0
        self.time_spent_in_main=tspent
        log(render("{RED}finished main{/} in {MAGENTA}%.5lg seconds{/}"%tspent),'{log:resources}')
        self.report_runtime("done in %g seconds"%tspent)
        self.note_resource_stats({'resource_type':'runtime','seconds':tspent})

        self.default_log_level=dll
        #self.runtime_update("storing")

        if mr is not None:
            log("main returns",mr,"attaching to the object as list")

            if isinstance(mr, collections.Iterable):
                mr=list(mr)
            else:
                mr=[mr]
            for r in mr:
                if isinstance(r,DataAnalysis):
                    log("returned dataanalysis:",r,"assumptions:",r.assumptions)
            setattr(self,'output',mr)

    def process_find_output_objects(self):
        if self._da_ignore_output_objects:
            return []

        da=list(objwalk(self.export_data(),sel=lambda y:isdataanalysis(y)))
        if da!=[]:
            log(render("{BLUE}resulting object exports dataanalysis, should be considered:{/}"),da)
            log(render("{RED}carefull!{/} it will substitute the object!"),da)

            if len(da)==1:
                da=da[0]
        return da

    def process_implement_output_objects(self,output_objects,implemented_objects):
        log("was",output_objects,level='output_objects')
        log("has",implemented_objects,level='output_objects')


        try:
            for newobj,obj in zip(implemented_objects,output_objects):
                log("replace",obj,"with",newobj,level='top')
        except TypeError:
            implemented_objects=[implemented_objects]
            output_objects=[output_objects]

        for newobj,obj in zip(implemented_objects,output_objects):
            log("replace",obj,"with",newobj,level='top')

            #for key in newobj.))dir:
            for key in newobj.export_data().keys(): # or all??
                setattr(obj,key,getattr(newobj,key))

    def get_delegation(self):
    #def list_delegated(self):
        #if self._da_delegated_input is not None:
        #   if self._da_main_delegated is not None:
        #       raise Exception("core design error! main is delegated as well as input! ")
        #   return self._da_delagated_input
        if self._da_main_delegated is not None:
            return self._da_main_delegated

    def process_list_delegated_inputs(self,input):
        return [] # disabled

        # walk input recursively
        if isinstance(input,list) or isinstance(input,tuple):
            delegated_inputs=[]
            for input_item in input:
                delegated_inputs+=self.process_list_delegated_inputs(input_item)
            return delegated_inputs

        if isinstance(input,DataAnalysis):
            d=input.get_delegation()
            if d is not None:
                log("input delegated:",input,d)
                return [d]
            return []

        raise Exception("can not understand input: "+repr(input))

    def process_list_analysis_exceptions(self,input):
        # walk input recursively
        if isinstance(input,list) or isinstance(input,tuple):
            l=[]
            for input_item in input:
                l+=self.process_list_analysis_exceptions(input_item)
            return l

        if isinstance(input,DataAnalysis):
            if hasattr(input,'analysis_exceptions'):
                return input.analysis_exceptions
            return []

        if input is None:
            log("input is None, it is fine")
            return []

        raise Exception("can not understand input: "+repr(input))

    def process_verify_inputs(self,input):
        # walk input recursively
        if not self.force_complete_input:
            log("loose input evaluation - not forced")
            return

        if isinstance(input,list) or isinstance(input,tuple):
            for input_item in input:
                self.process_verify_inputs(input_item)
            return

        if isinstance(input,DataAnalysis):
            log("will verify:",input)
            if not input._da_locally_complete:
                log("input is not completed! this should not happen!",input)
                raise("input is not completed! this should not happen!")
            return

        if input is None:
            log("input is None, it is fine")
            return

        raise Exception("can not understand input: "+repr(input))

    use_hashe=None

    def process_substitute_hashe(self,fih):
        if self.use_hashe is not None:
            substitute_hashe=self.use_hashe[0]
            hashe_mappings=self.use_hashe[1:]

            for a,b in hashe_mappings:
                log("mapping",a,b,getattr(self,b)._da_expected_full_hashe)
                substitute_hashe= hashtools.hashe_replace_object(substitute_hashe, a, getattr(self, b)._da_expected_full_hashe)

            log("using substitute hashe:",substitute_hashe)
            log("instead of:",fih)
            return substitute_hashe
        else:
            return fih

    report_runtime_destination=None
    runtime_id=None

    def report_runtime(self,message): # separet
        if self.report_runtime_destination is None: return
        try:
            if not self.report_runtime_destination.startswith("mysql://"): return
            dbname,table=self.report_runtime_destination[8:].split(".")
            print("state goes to",dbname,table)

            import MySQLdb
            db = MySQLdb.connect(host="apcclwn12",
                      user="root",
                      port=42512,
                      #unix_socket="/workdir/savchenk/mysql/var/mysql.socket",
                      passwd=open(os.environ['HOME']+"/.secret_mysql_password").read().strip(), # your password
                      db=dbname)

            import socket

            if self.runtime_id is None:
                import random
                self.runtime_id=random.randint(0,10000000)

            cur=db.cursor()
            cur.execute("INSERT INTO "+table+" (analysis,host,date,message,id) VALUES (%s,%s,NOW(),%s,%s)",(self.get_version(),socket.gethostname(),message,self.runtime_id))

            db.commit()
            db.close()

        except Exception as e:
            print("failed:",e)


    def process(self,process_function=None,restore_rules=None,restore_config=None,requested_by=None,**extra):
        log(render("{BLUE}PROCESS{/}"))

        if requested_by is None:
            requested_by=['direct']

        log('cache assumptions:',AnalysisFactory.cache_assumptions,'{log:top}')
        log('object assumptions:',self.assumptions,'{log:top}')


        restore_config=self.process_restore_config(restore_config)
        restore_rules=self.process_restore_rules(restore_rules,extra)

        log(render("{BLUE}requested "+("OUTPUT" if restore_rules['output_required'] else "")+" by{/} "+" ".join(requested_by)),'{log:top}')
        requested_by=[("+" if restore_rules['output_required'] else "-")+self.get_version()]+requested_by

        self._da_requested_by=requested_by

        self.process_checkin_assumptions()

        rr= dict(restore_rules.items() + dict(output_required=False).items()) # no need to request input results unless see below

        #### process input
        input_hash,input=self.process_input(obj=None,
                                            process_function=process_function,
                                            restore_rules=update_dict(restore_rules,dict(
                                                                                            output_required=False,
                                                                                            can_delegate=restore_rules['can_delegate_input'])),
                                            requested_by=["input_of"]+requested_by)
        # TODO: defaults, alternatives
        #### /process input

        process_t0=time.time()

        log("input hash:",input_hash)
        log("input objects:",input)

        fih=('analysis',input_hash,self.get_version()) # construct hash
        log("full hash:",fih)

        fih=self.process_substitute_hashe(fih)

        self._da_expected_full_hashe=fih

        substitute_object=None

        if restore_rules['output_required']: #
            log("output required, try to GET from cache")
            if self.retrieve_cache(fih,restore_config): # will not happen with self.run_for_hashe
                log("cache found and retrieved",'{log:top}')
                log(fih,'{log:top}')
            else:
                log("no cache",'{log:top}')
                log(fih,'{log:top}')

                if hasattr(self,'produce_disabled') and self.produce_disabled:
                    if restore_rules['force_complete']:
                        raise Exception("not allowed to produce but has to! at "+repr(self)+"; hashe: "+repr(fih))
                    else:
                        self.incomplete=True
                        return fih,self


                if restore_rules['explicit_input_required']:
                    log("exclicite input is available")
                else:
                    log("need to guarantee that explicit input is available")

                    ## if output has to be generated, but explicite input was not prepared, do it
                    ## process
                    return self.process(process_function=process_function,
                                        restore_rules=update_dict(restore_rules,dict(explicit_input_required=True)),requested_by=['output_required_by_parent']+requested_by )
                                        #restore_rules=update_dict(restore_rules,dict(output_required=True,explicit_input_required=True)) )
                    ##  /process

                delegated_inputs=self.process_list_delegated_inputs(input)
                if delegated_inputs!=[]:
                    log("some input was delegated:",delegated_inputs)
                    log(render("{RED}waiting for delegated input!{/}"))
                    self._da_delegated_input=delegated_inputs

                if restore_rules['can_delegate'] and self.cached:
                    log("will delegate this analysis")
                    hashekey=self.cache.register_delegation(self,fih)
                    self._da_main_delegated=hashekey
                    return fih,self # RETURN!

             # check if can and inpust  relaxe

                if delegated_inputs!=[]:
                    log("analysis design problem! input was delegated but the analysis can not be. wait until the input is done!")
                    raise

                self.process_verify_inputs(input)

                # check if input had exceptions
                analysis_exceptions=self.process_list_analysis_exceptions(input)
                if analysis_exceptions!=[]:
                    log("found analysis exceptions in the input:",analysis_exceptions)
                    if not self.treat_input_analysis_exceptions(analysis_exceptions):
                        if not hasattr(self,'analysis_exceptions'):
                            self.analysis_exceptions=[]
                        self.analysis_exceptions+=analysis_exceptions
                        log(render("{RED}ANALYSIS EXCEPTIONS:{/}"),analysis_exceptions,level='top')
                    else:
                        analysis_exceptions=[]
                # exceptions

                if analysis_exceptions==[]:
                    if restore_rules['run_if_can_not_delegate']:
                        log("no way was able to delegate, but all ready to run and allowed. will run")
                    else:
                        log("not allowed to run here. hopefully will run as part of higher-level delegation")
                        raise Exception("not allowed to run but has to (delegation)!")
                        return fih,self # RETURN!

                    if restore_rules['run_if_haveto'] or self.run_for_hashe:

                        mr=self.process_run_main() # MAIN!
                        self.process_timespent_interpret()
                    else:
                        raise Exception("not allowed to run but has to! at "+repr(self))

                    #log("new output:",self.export_data())

                    if self.rename_output_unique and restore_config['datafile_restore_mode']=="copy":
                        self.process_output_files(fih)
                    else:
                        log("disabled self.rename_output_unique",level='cache')

                    self.store_cache(fih)
                    #self.runtime_update("done")

            output_objects=self.process_find_output_objects()
            if output_objects!=[]:
                da=output_objects
                if self.cached:
                    log(render("{RED}can not be cached - can not save non-virtual objects! (at the moment){/}"),da)
                    self.cached=False


                #restore_rules_for_substitute=update_dict(restore_rules,dict(explicit_input_required=False))
                restore_rules_for_substitute=update_dict(restore_rules,dict(explicit_input_required=restore_rules['substitute_output_required']))
                self.force_complete_input=restore_rules['force_complete'] # ?.. !!!!
                log(render("{RED}will process substitute object as input with the following rules:{/}"),restore_rules_for_substitute)

                rh,ro=self.process_input(da,restore_rules=restore_rules_for_substitute,requested_by=['output_of']+requested_by)
                log(render("substitute the object with dynamic input. rh:"),rh)
                log(render("substitute the object with dynamic input. ro:"),ro)


                log("--- old input hash:",fih)
                if self.allow_alias:
                    self.register_alias(fih,rh)
                    self.process_implement_output_objects(output_objects,ro)
                else:
                    log("alias is not allowed: using full input hash!")
                    fih=rh
                    substitute_object=ro
                    log("+++ new input hash:",fih)

            log("processing finished, main, object is locally complete")
            log("locally complete:",id(self))
            log("locally complete:",fih,'{log:top}')
            self._da_locally_complete=fih
        else:
            log("NO output is strictly required, will not attempt to get")
            if restore_rules['restore_complete']:
                log("however, diagnostic complete restore is requested, trying to restore")
                if self.retrieve_cache(fih,restore_config):
                    log("cache found and retrieved",'{log:top}')
                    log("processing finished, object is locally complete")
                    self._da_locally_complete=fih
                    log("locally complete:",fih,'{log:top}')
                else:
                    log("NO cache found",'{log:top}')

        self.process_checkout_assumptions()

        process_tspent=time.time()-process_t0
        log(render("{MAGENTA}process took in total{/}"),process_tspent)
        self.note_resource_stats({'resource_type':'usertime','seconds':process_tspent})
        self.summarize_resource_stats()

        return_object=self
        if substitute_object is not None:
            log("returning substituted object")
            return_object=substitute_object

        log("PROCESS done",fih,return_object)
        return fih,return_object

    def register_alias(self,hash1,hash2):
        log("alias:",hash1)
        log("stands for",hash2)
        self.alias=hash2
        AnalysisFactory.register_alias(hash1,hash2)

    def process_input(self,obj=None,process_function=None,restore_rules=None,restore_config=None,requested_by=None,**extra):
        """
        walk over all input; apply process_function and implement if neccessary
        """

        log("{CYAN}PROCESS INPUT{/}")

        restore_rules_default=dict(explicit_input_required=False,restore_complete=False)
        restore_rules=dict(restore_rules_default.items()+restore_rules.items() if restore_rules is not None else [])

        # to simplify input
        for k in extra.keys():
            if k in restore_rules:
                restore_rules[k]=extra[k]

        if restore_config is None:
            restore_config={}

        if self.copy_cached_input:
            #log("will copy cached input")
            restore_config['datafile_restore_mode']="copy"
        else:
            #log("will NOT copy cached input")
            restore_config['datafile_restore_mode']="url_in_object"

        if self.test_files: # may be not boolean
            restore_config['test_files']=True
        else:
            restore_config['test_files']=False

        if self.force_complete_input:
            restore_rules['force_complete']=True
        else:
            restore_rules['force_complete']=False
            log("input will not be forced!")


        log("input restore_rules:",restore_rules)
        log("input restore_config:",restore_config)

        if obj is None:
            # start from the object dir, look for input
            inputhashes=[]
            inputs=[]
            for a in dir(self):
                if a.startswith("input"):
                    o=getattr(self,a)
                    log("input item",a,o)
                    if o is NoAnalysis:
                        log("NoAnalysis:",o) #,o.__class__)
                        continue # yes?

                    if o is None:
                        raise Exception("input is None: virtual class: "+repr(self)+" input "+a+" requested by "+" ".join(requested_by))

                    h,l=self.process_input(obj=o,process_function=process_function,restore_rules=restore_rules,restore_config=restore_config,requested_by=requested_by)

                    if not isinstance(l,list) and l.is_noanalysis():
                        log("NoAnalysis:",o,o.__class__)
                        continue # yes?

                    if l is not None:
                        log("input item",a)
                        log("implemented as",h,l)
                        setattr(self,a,l)
                    else:
                        log("input item None!",a,l)
                        raise Exception("?")

                    inputhashes.append(h)
                    inputs.append(l)

            if len(inputhashes)>1:
                return ('list',)+tuple(inputhashes),inputs
            if len(inputhashes)==1:
                return inputhashes[0],inputs[0]

            log("this class has no input! origin class")
            # does this ever happen?
            return None,None
        else:
            # process given input structure
            log("parse and get",obj,obj.__class__)

            # list or tuple
            if isinstance(obj,list) or isinstance(obj,tuple):
                log("parse list")
                hashes=[]
                nitems=[]
                for i in obj:
                    log("item:",i)
                    hi,ni=self.process_input(obj=i,process_function=process_function,restore_rules=restore_rules,restore_config=restore_config,requested_by=requested_by)
                    hashes.append(hi)
                    nitems.append(ni)
                if all([i is None for i in nitems]):
                    return tuple(['list']+hashes),None

                if any([i is None for i in nitems]):
                    raise Exception("process input returned None for a fraction of a structured input! this should not happen")

                return tuple(['list']+hashes),nitems

       # we are down to the input item finally

        item=self.interpret_item(obj)  # this makes DataAnalysis object
        #if hasattr(item,'noanalysis') and item.noanalysis:
        #    log("noanalysis!")
        if item.is_noanalysis():
            log("noanalysis!")
            return None,item

        rr=dict(restore_rules.items()+dict(explicit_input_required=False,output_required=restore_rules['explicit_input_required']).items())
        if self.run_for_hashe:
            log("for run_for_hashe, input need a right to run")
            restore_rules['run_if_haveto']=True


        log("proceeding to run",item,"rules",restore_rules)

        try:
            log("item:",item._da_locally_complete)
        except Exception as e:
            raise Exception(str(item)+" has no locally complete!")
        input_hash,newitem=item.process(process_function=process_function,restore_rules=rr,restore_config=restore_config,requested_by=requested_by) # recursively for all inputs process input
        log("process_input finishing at the end",input_hash,newitem)

        if process_function is not None:
            process_function(self,newitem) # then run something to each input item

        return input_hash,newitem # return path to the item (hash) and the item

    #def get_output_hash(self):
    #    return shhash(tuple(sorted(self.export_data().items())))

    _da_resource_stats=None

    def is_noanalysis(self):
        if not hasattr(self,'noanalysis'): return False
        if isinstance(self,NoAnalysis): return True
        return self.noanalysis

    def note_resource_stats(self,info):
        if self._da_resource_stats is None:
            self._da_resource_stats=[]
        log('note resource stats:',info['resource_type'],'{log:resources}')
        self._da_resource_stats.append(info)

    def summarize_resource_stats(self):
        total_usertime=sum([a['seconds'] for a in self._da_resource_stats if a['resource_type']=='usertime'])
        log(render("collected resource stats, total {MAGENTA}usertime{/}"),total_usertime,'{log:resources}')

        total_runtime=sum([a['seconds'] for a in self._da_resource_stats if a['resource_type']=='runtime'])
        log(render("collected resource stats, total {MAGENTA}run time{/}"),total_runtime,'{log:resources}')

        total_cachetime=sum([a['stats']['copytime'] for a in self._da_resource_stats if a['resource_type']=='cache'])
        log(render("collected resource stats, total {MAGENTA}cache copy time{/}"),total_cachetime,'{log:resources}')

        self.resource_stats={
                                'total_usertime':total_usertime,
                                'total_runtime':total_runtime,
                                'total_cachetime':total_cachetime
                            }


    def __call__(self):
        return self

    def __repr__(self):
        return "[%s%s]"%(self.get_version(),";NoneInTheInput" if self.virtual else "")

        #if hasattr(self,'_da_attributes'):
        #    return "[%s: %s: %s]"%(self.__class__.__name__,repr(self._da_attributes),self.version)
        #return "[%s: %s]"%(self.__class__.__name__,self.version)
        #return "[%s: %s %s]"%(self.__class__.__name__,self.version,("%.12x"%id(self))[-6:]) # note that instances are different; take same instance by name from a dict

class Data(DataAnalysis):
    """
    data runs trivilarily: only returns hash of its content
    """

    def get(self,path):
        pass



class FileHashed(DataAnalysis):
    input_filename=None

    cached=False # never
    infactory=False
    run_for_hashe=True


    def main(self): # pointless unless fine has known hashe!
        self.md5= hashtools.hash_for_file(open(self.input_filename.handle))
        return DataHandle(self.input_filename.handle+":md5:"+self.md5[:8])

    def get_filename(self):
        return self.input_filename.str()

class HashedFile(DataAnalysis):
    filename=None
    md5=None

    cached=False # never
    infactory=False

    def get_signature(self):
        if self.filename is not None:
            return "File:"+os.path.basename(self.filename)+":"+self.md5[:5]
        else:
            return "File: None"

class HasheForFile(DataAnalysis):
    input_filename=None

    cached=False # never
    infactory=False
    run_for_hashe=True


    def main(self):
        md5= hashtools.hash_for_file(open(self.input_filename.str()))
        return HashedFile(use_md5=md5,use_filename=self.input_filename.str())

class DataHandle(DataAnalysis):
    infactory=False
    trivial = True

    def __new__(self,*a,**args): # not only kw
        return object.__new__(self)

    def __init__(self,h=None,update=False):
        self.handle=h

    def process(self,**args):
        log("datahandle is hash",self)
        self._da_locally_complete=True
        return self.handle,self

    def __repr__(self):
        return '[%s]'%self.handle


class DataAnalysisGroup(DataAnalysis): # make it
    def process(self):
        pass

# imported

# abstract

class AnyAnalysis(DataAnalysis):
    def main(self):
        raise Exception("requested to run abstract any analysis!")


class DataFile(DataAnalysis):
    cached_path_valid_url=False

    infactory=False

    size=None

    trivial=True

    def __init__(self,fn=None,update=False):
        self.path=fn
        self.size=os.path.getsize(fn)

    def get_cached_path(self): # not work properly if many run!
        return self.cached_path if hasattr(self,'cached_path') else self.path

    def get_path(self): # not work properly if many run!
# confis
        #log("get path:",self,self.cached_path,self.cached_path_valid_url) #,self.restored_mode)

        if hasattr(self,'cached_path'):
            print("have cached path",self.cached_path)

        if hasattr(self,'cached_path') and self.cached_path_valid_url:
            return self.cached_path

        if hasattr(self,'_da_unique_local_path'):
            return self._da_unique_local_path

        if not hasattr(self,'restored_mode'): # means it was just produced
            return self.path

        if self.restored_mode=="copy":
            log("datafile copied but no local path?",self,id(self))
            raise Exception("inconsistency: "+repr(self))
            
    def get_full_path(self):
        if hasattr(self,'restored_path_prefix'):
            return self.restored_path_prefix+"/"+self.get_path()
        else:
            if hasattr(self,'cached_path') and self.cached_path_valid_url:
                return self.cached_path
            else:
                raise Exception("unable to construct full path!")

    def open(self):
        return gzip.open(self.cached_path) if hasattr(self,'cached_path') else open(self.path)

    def __repr__(self):
        return "[DataFile:%s]"%(self.path if hasattr(self,'path') else 'undefined')
                        

    def jsonify(self):
        if self.size<100e3:
            try:
                return json.load(self.open())
            except:    
                content=self.open().read()

            try:
                from astropy.io import fits
                return jsonify.jsonify_fits(fits.open())
            except Exception as e:
                print("can not interpret as fits:",e)
            
            try:
                json.dumps(content)
                return content
            except:
                content=self.open().read()
                return str(self)+" can not encode "+str(self.size)+" fits error "+str(e)
        else:
            return str(self)+" too big "+str(self.size)


class DataFileStatic(DataFile):
    cached_path_valid_url=False

    def __init__(self,fn=None):
        self.path=fn

    def get_cached_path(self): # not work properly if many run!
        return self.path
    
    def get_path(self): # not work properly if many run!
        return self.path

    def open(self):
        return gzip.open(self.cached_path) if hasattr(self,'cached_path') else open(self.path)

    def __repr__(self):
        return "[DataFileStatic:%s]"%(self.path if hasattr(self,'path') else 'undefined')

def reset():
    AnalysisFactory.reset()
    TransientCacheInstance.reset()


def debug_output():
    printhook.global_all_output=True
    printhook.global_permissive_output=True
    printhook.global_fancy_output=True
    printhook.LogStreams=[printhook.LogStream(sys.stdout,levels=None,name="original stdout set in debug")]

AnalysisFactory.blueprint_class=DataAnalysis
AnalysisFactory.blueprint_DataHandle=DataHandle

byname = lambda x: AnalysisFactory.byname(x)

def get_object(a):
    return AnalysisFactory[a]
