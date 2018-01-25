import re

import dataanalysis.caches.cache_core
import dataanalysis.core as da
from dataanalysis.printhook import log


class DelegatedNoticeException(da.AnalysisDelegatedException):
    pass

class WaitingForDependency(da.AnalysisDelegatedException):
    def __init__(self, hashe, resources):
        self.hashe=hashe
        self.resources=resources


class DelegatingCache(dataanalysis.caches.cache_core.Cache):
    def delegate(self, hashe, obj):
        pass

    def find_content_hash_obj(self,hashe,obj):
        delegation_state=self.delegate(hashe, obj)
        raise da.AnalysisDelegatedException(hashe,origin=repr(self),delegation_state=delegation_state)

class SelectivelyDelegatingCache(DelegatingCache):
    delegating_analysis=None

    def will_delegate(self,hashe,obj=None):
        log("trying for delegation",hashe)

        if self.delegating_analysis is None:
            log("this cache has no delegations allowed")
            return False

        if any([hashe[-1] == option or re.match(option,hashe[-1]) for option in self.delegating_analysis]):
            log("delegation IS allowed")
            return True
        else:
            log("failed to find:",hashe[-1],self.delegating_analysis)
            return False

    def restore(self,hashe,obj,restore_config=None):
        if self.will_delegate(hashe, obj):
            return super(SelectivelyDelegatingCache, self).restore(hashe, obj, restore_config)
        else:
            return self.restore_from_parent(hashe, obj, restore_config)

