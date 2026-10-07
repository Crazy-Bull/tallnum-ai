"""Compile the established binary/nearest-ternary recipe into v2 contracts."""
from fractions import Fraction
from .planner import Planner, ordinary
from .route_search import Block


def legacy_structure(search):
    planner=Planner(search.catalog)
    def leaves(cells,target,kind):
        if cells==5 or target<48:return [(target,kind)]
        pair=planner.triple(target) if cells==6 and kind=='match' else None
        if pair:
            a,b=pair
            return leaves(6,a,'single')+[(a,'match'),(b,'extend')]
        if target%2 or not ordinary(target//2):raise ValueError('No established recipe')
        return leaves(cells,target//2,'single')+leaves(cells-1,target//2,'match')
    try:
        if search.initial:
            if search.initial!=(Block(search.target//2),):return None
            recipe=leaves(search.cells-1,search.target//2,'match')
        else:recipe=leaves(search.cells,search.target,'single')
        board=search.initial;steps=[];units=Fraction(0)
        for target,kind in recipe:
            found=next((x for x in search.successors(board) if x[0]['kind']=='leaf'
                        and x[0]['target']==target and x[0]['exit']==kind),None)
            if found is None:return None
            op,after,cost=found
            steps.append({**op,'before':[b.json() for b in board],'after':[b.json() for b in after]})
            board=after;units+=cost
        if board!=(Block(search.target),):return None
        return {'steps':steps,'units':str(units),'baseline':True}
    except ValueError:return None
