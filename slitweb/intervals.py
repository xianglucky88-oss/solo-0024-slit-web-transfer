def union(spans):
    result = []
    for a,b in sorted(spans):
        if not result or a > result[-1][1]:
            result.append([a,b])
        else:
            result[-1][1] = max(b,result[-1][1])
    return result


def measure(spans):
    return sum(b - a for a, b in union(spans))


def gaps(spans, end):
    last = 0
    result = []
    for a,b in union(spans):
        if a > last:
            result.append([last,a])
        last = b
    if last < end:
        result.append([last,end])
    return result
