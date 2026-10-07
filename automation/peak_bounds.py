"""Fast all-number minimax relaxation, used only as rigorous LOWER bounds.

Group construction and physical space are relaxed, never certified here.
Every real ordinary block comes from an input, equal-value merge or EDGE;
at most one Group exists, so an EDGE pair has an ordinary predecessor.
"""
import heapq


def arithmetic_peak_bounds(inputs, initial, maximum):
    past = max((b.value for b in initial),default=0)
    costs,recipes = {},{}
    queue,done = [],set()

    def relax(value,peak,recipe):
        if not 1 <= value <= maximum:
            return
        if value not in costs or peak<costs[value]:
            costs[value] = peak
            recipes[value] = recipe
            heapq.heappush(queue,(peak,value))

    for value in inputs:
        relax(value,max(past,value),{'kind':'input','value':value})
    for block in initial:
        if not block.group:
            relax(block.value,past,{'kind':'initial','value':block.value})
    while queue:
        peak,value = heapq.heappop(queue)
        if value in done or peak!=costs[value]:
            continue
        done.add(value)
        relax(2*value,max(peak,2*value),{'kind':'equal-merge','ordinary':value,'copies':2})
        decade = value//10
        if decade:
            # A relaxed Group may have any even total >=6 or odd total >=17.
            # Two equal ordinary values would auto-merge before EDGE.
            other = next((n for n in range(10*decade,min(maximum,10*decade+9)+1)
                          if n!=value and (n>=6 and n%2==0 or n>=17 and n%2==1)),None)
            if other is not None:
                relax(2*decade,max(peak,other),{'kind':'edge','ordinary':value,
                                              'group':other,'groupConstructionVerified':False})
    return {'costs':costs,'recipes':recipes,'initialPeak':past,
            'meaning':'necessary arithmetic lower bound; Group generation and physical space relaxed',
            'groupConstructionVerified':False,'physicalSpaceVerified':False}
