# =============================================================================
# V2 Application Routing — adds listener rules to V1's ALB (non-destructive)
#
# V1 API rule:     priority 10, paths: /api/*, /health, /docs, /openapi.json
# V1 default:      forward to V1 UI target group
#
# V2 API:          PRIVATE — no listener rule, reachable only via Cloud Map
# V2 UI rule:      priority 6, paths: /v2/* (only public V2 route)
# V1 default:      UNCHANGED — still forwards to V1 UI
#
# Cutover: later change default action from V1 UI → V2 UI (not in this file)
# =============================================================================

# --- V2 API Target Group ---

resource "aws_lb_target_group" "v2_api" {
  count       = var.deploy_app ? 1 : 0
  name        = "${var.project_name}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 3
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = {
    Name    = "${var.project_name}-api-tg"
    Project = var.project_name
  }
}

# --- V2 UI Target Group ---

resource "aws_lb_target_group" "v2_ui" {
  count       = var.deploy_app ? 1 : 0
  name        = "${var.project_name}-ui-tg"
  port        = 8501
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/v2/_stcore/health"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 3
    unhealthy_threshold = 3
    matcher             = "200"
  }

  tags = {
    Name    = "${var.project_name}-ui-tg"
    Project = var.project_name
  }
}

# --- V2 API is PRIVATE — no ALB listener rule ---
# The API is only reachable via Cloud Map (api.meeting-intel-v2.local:8000).
# The target group is kept for ALB-based health monitoring, but no external
# traffic is routed to the API.
# Removed: aws_lb_listener_rule.v2_api (was priority 5, path /api/v2/*)

# --- V2 UI Listener Rule (priority 6 — V2 UI accessible at /v2/*) ---
# During transition, V2 UI at /v2/* while V1 UI stays as default

resource "aws_lb_listener_rule" "v2_ui" {
  count        = var.deploy_app ? 1 : 0
  listener_arn = data.aws_lb_listener.http.arn
  priority     = 6

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.v2_ui[0].arn
  }

  condition {
    path_pattern {
      values = ["/v2/*"]
    }
  }

  tags = {
    Name    = "${var.project_name}-ui-rule"
    Project = var.project_name
  }
}
