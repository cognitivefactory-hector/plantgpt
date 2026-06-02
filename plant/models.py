# Django discovers an app's models from `<app>.models`. The domain model is organized
# under the `plant.model` subpackage (per PLAN.md's layout), so re-export it here.
from plant.model.models import *  # noqa: F401,F403
