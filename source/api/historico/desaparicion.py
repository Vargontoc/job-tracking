"""Evaluador de desaparición y contador de ausencias consecutivas.

Recibe las ofertas vigentes sin ``fecha_fin_difusion``, el listado oficial
del día y los códigos con error por oferta de la última pasada; excluye las
que estén en ``errores_por_oferta`` (REQ-007/ALT-003) y las que estén en
estado ``sin_ficha`` (REQ-009); registra en ``historico-presencia-repository``
la presencia o ausencia de cada código candidata para la fecha del listado;
cuenta las ausencias consecutivas consultando el histórico de presencia con
el número de ausencias configurado (por defecto ``2``, con el margen de un
día) y cierra de forma idempotente, a través de ``persistencia-adapter``,
las que hayan faltado en los últimos listados consecutivos. Si la fuente de
respaldo no está disponible o devuelve error, no cierra ninguna oferta y
registra la abstención (ALT-004). Una oferta cerrada que reaparece no se
reabre (ALT-007/DEC-004).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from source.api.historico.persistencia_client import (
    ErrorPersistencia,
    Oferta,
)


# ---------------------------------------------------------------------------
# Dataclass de resultado
# ---------------------------------------------------------------------------


@dataclass
class ResultadoDesaparicion:
    """Resultado de evaluar la desaparición de ofertas del listado oficial.

    Atributos:
        cerradas: Códigos de las ofertas que se cerraron correctamente.
        errores: Mensajes de error para las ofertas que no se pudieron
            cerrar o cuyo registro de presencia falló.
    """

    cerradas: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Evaluador
# ---------------------------------------------------------------------------


class EvaluadorDesaparicion:
    """Evaluador de desaparición y ausencias consecutivas.

    Recibe las ofertas vigentes sin ``fecha_fin_difusion``, el listado
    oficial del día y los códigos con error; excluye las que estén en
    ``errores_por_oferta`` y las ``sin_ficha``; registra presencia/ausencia;
    cuenta ausencias consecutivas y cierra idempotentemente las que hayan
    faltado N listados consecutivos.

    Args:
        repositorio_presencia: Repositorio de presencia en listado
            (TASK-005).
        cliente_persistencia: Cliente de ``persistencia-api`` para cerrar
            ofertas (TASK-009).
        abstenciones: Repositorio de abstenciones de cierre (TASK-006).
        n_ausencias: Número de ausencias consecutivas requeridas para
            cerrar (por defecto 2, margen de un día).
    """

    def __init__(
        self,
        repositorio_presencia: object,
        cliente_persistencia: object,
        abstenciones: object,
        n_ausencias: int = 2,
    ) -> None:
        self._repositorio = repositorio_presencia
        self._cliente = cliente_persistencia
        self._abstenciones = abstenciones
        self._n_ausencias = n_ausencias

    def evaluar(
        self,
        ofertas_vigentes: list[Oferta],
        listado_oficial: set[str],
        errores_por_oferta: set[str],
        fecha_listado: str,
    ) -> ResultadoDesaparicion:
        """Evalúa la desaparición de ofertas del listado oficial.

        Para cada oferta vigente sin ``fecha_fin_difusion``:

        - Excluye las que estén en estado ``sin_ficha`` (REQ-009).
        - Excluye las cuyo código esté en ``errores_por_oferta``
          (REQ-007/ALT-003); registra abstención con el código y motivo.
        - Registra presencia o ausencia en el repositorio para la fecha
          del listado (REQ-005).
        - Consulta las últimas N apariciones; si todas son ausencias,
          cierra la oferta a través del cliente de persistencia.
        - Si presente en alguna de las últimas N → mantener vigente.

        Los errores al cerrar se capturan sin lanzar excepción.

        Args:
            ofertas_vigentes: Ofertas vigentes sin ``fecha_fin_difusion``
                (candidatas al cierre por desaparición).
            listado_oficial: Conjunto de códigos del listado oficial del
                día.
            errores_por_oferta: Conjunto de códigos con error en la última
                pasada del buscador (REQ-007).
            fecha_listado: Fecha del listado oficial (ISO ``YYYY-MM-DD``).

        Returns:
            Resultado con las cerradas y los errores.
        """
        resultado = ResultadoDesaparicion()

        for oferta in ofertas_vigentes:
            # Excluir sin_ficha (REQ-009).
            if oferta.estado == "sin_ficha":
                continue

            # Excluir códigos con error (REQ-007/ALT-003).
            if oferta.codigo in errores_por_oferta:
                try:
                    self._abstenciones.registrar(
                        motivo=(
                            "Código con error en la pasada del buscador"
                        ),
                        timestamp=fecha_listado,
                        codigos_afectados=[oferta.codigo],
                    )
                except Exception:
                    # No lanzar excepción por error en abstención.
                    pass
                continue

            # Determinar presencia/ausencia en el listado oficial.
            presente = oferta.codigo in listado_oficial

            # Registrar presencia/ausencia en el repositorio (REQ-005).
            try:
                if presente:
                    self._repositorio.registrar_presencia(
                        oferta.comunidad, oferta.codigo, fecha_listado
                    )
                else:
                    self._repositorio.registrar_ausencia(
                        oferta.comunidad, oferta.codigo, fecha_listado
                    )
            except Exception as exc:
                resultado.errores.append(
                    f"Error al registrar presencia/ausencia para la oferta "
                    f"{oferta.codigo}: {exc}"
                )
                continue

            # Consultar ausencias consecutivas.
            try:
                hay_n_ausencias = self._repositorio.ausencias_consecutivas(
                    oferta.codigo, oferta.comunidad, self._n_ausencias
                )
            except Exception as exc:
                resultado.errores.append(
                    f"Error al consultar ausencias de la oferta "
                    f"{oferta.codigo}: {exc}"
                )
                continue

            # Si ausente en las últimas N fechas → cerrar (REQ-005).
            if hay_n_ausencias:
                fecha_cierre = fecha_listado
                try:
                    cierre = self._cliente.cerrar_oferta(
                        oferta.comunidad, oferta.codigo, fecha_cierre
                    )
                    if isinstance(cierre, ErrorPersistencia):
                        resultado.errores.append(
                            f"Error al cerrar la oferta {oferta.codigo}: "
                            f"{cierre.motivo}"
                        )
                    elif cierre is True:
                        resultado.cerradas.append(oferta.codigo)
                    elif cierre is False:
                        resultado.errores.append(
                            f"La oferta {oferta.codigo} no existe en "
                            f"persistencia y no se puede cerrar."
                        )
                except Exception as exc:
                    resultado.errores.append(
                        f"Error al cerrar la oferta {oferta.codigo}: {exc}"
                    )

        return resultado
