"""
Módulo centralizado de permisos por rol.

Se usa desde cualquier vista para preguntar "¿este usuario puede hacer X?"
en vez de repetir comparaciones de rol sueltas por todos lados. Así, si el
día de mañana cambian las reglas de negocio, se edita en un solo lugar.
"""


def es_admin(usuario: dict) -> bool:
    """True si el usuario logueado tiene rol 'admin' (control total del sistema)."""
    return (usuario or {}).get("rol") == "admin"


def es_gerente_o_admin(usuario: dict) -> bool:
    """True si el usuario es 'gerente' o 'admin' (acceso a reportes/paneles)."""
    return (usuario or {}).get("rol") in ("admin", "gerente")


def es_operador(usuario: dict) -> bool:
    """True si el usuario es 'operador' (solo puede reportar fallas)."""
    return (usuario or {}).get("rol") == "operador"


def puede_editar_ot(usuario: dict, ot: dict) -> bool:
    """
    Reglas de edición de una OT:
    - Admin: puede editar cualquier OT, sin restricciones.
    - Técnico: puede editar si la OT es suya o si todavía está sin asignar
      (backlog compartido).
    - Cualquier otro rol: no puede editar OTs.
    """
    if es_admin(usuario):
        return True
    if (usuario or {}).get("rol") == "tecnico":
        return ot.get("tecnico_id") == usuario.get("tecnico_id") or ot.get("tecnico_id") is None
    return False