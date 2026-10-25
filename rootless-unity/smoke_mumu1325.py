"""Owned ABI: post-city-select read budget must not replay Select or Apply."""
from pathlib import Path
import sys
from search_city import build
from smoke_search_city import one


def main(library):
    library=Path(library).resolve(strict=True)
    anchor="   if(n.phase==='wait-city-return'){"
    for condition,expected in (("n.city_read_budget_retries===0",'navigation-ready'),('true','frame-budget')):
        source=build('Pskov')
        assert source.count(anchor)==1
        source=source.replace(anchor,anchor+"if("+condition+")fail('frame-budget');",1)
        value=one(library,300,source=source,expected_result=expected)
        n=value['navigation']
        assert n['city_select_attempted'] and n['city_select_completed']
        assert n['city_read_budget_retries']==(1 if expected=='navigation-ready' else 4)
        assert n['apply_completed']==(expected=='navigation-ready')
    print('Post-select read retry: one Select, at most one Apply, bounded persistent failure.')

if __name__=='__main__':main(sys.argv[1])
