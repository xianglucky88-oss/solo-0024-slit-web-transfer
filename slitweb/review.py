from .inspection import defect_review, face_coverage, fullwidth_segments, read_inspections
from .provenance import inspection_origin, shared_origins
from .salvage import length_losses, order_yield, read_orders, reusable_runs


def analyze_review(review, model, facts, outputs):
    inspections = read_inspections(review, model)
    orders = read_orders(review, model)
    runs = reusable_runs(model, outputs['exclusion'])
    segments = fullwidth_segments(model, inspections, facts['transfer'])
    salvageable = [row for row in segments if row['state'] == 'eligible']
    return dict(face=face_coverage(model, inspections, facts['coverage']),
                defect_review=defect_review(inspections, facts['transfer']),
                origin=inspection_origin(model, inspections),
                shared=shared_origins(model, facts['transfer'], facts['scrap']),
                runs=runs, yield_plan=order_yield(orders, runs),
                losses=length_losses(model, outputs['exclusion']),
                fullwidth=segments, fullwidth_yield=order_yield(orders, salvageable))
