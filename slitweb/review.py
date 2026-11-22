from .batching import batch_plan, read_batch_orders
from .inspection import defect_review, face_coverage, read_inspections
from .provenance import inspection_origin, shared_origins
from .salvage import length_losses, order_yield, read_orders, reusable_runs


def analyze_review(review, model, facts, outputs):
    inspections = read_inspections(review, model)
    orders = read_orders(review, model)
    runs = reusable_runs(model, outputs['exclusion'])
    batch, batch_cuts = batch_plan(read_batch_orders(review, model), runs, model)
    return dict(face=face_coverage(model, inspections, facts['coverage']),
                defect_review=defect_review(inspections, facts['transfer']),
                origin=inspection_origin(model, inspections),
                shared=shared_origins(model, facts['transfer'], facts['scrap']),
                runs=runs, yield_plan=order_yield(orders, runs),
                batch=batch, batch_cuts=batch_cuts,
                losses=length_losses(model, outputs['exclusion']))
