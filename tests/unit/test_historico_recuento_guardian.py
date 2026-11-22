"""Pruebas del guardián de recuento del listado (TASK-014)."""

import pytest

from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.presencia_repository import RepositorioPresencia
from source.api.historico.recuento_guardian import (
    GuardianRecuento,
    ResultadoValidacion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal."""
    return tmp_path / "test_guardian.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión, migra y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    migrar(conn)
    yield conn
    conn.close()


@pytest.fixture
def repo_presencia(conexion):
    """Repositorio de presencia sobre la BD migrada."""
    return RepositorioPresencia(conexion)


@pytest.fixture
def repo_abstenciones(conexion):
    """Repositorio de abstenciones sobre la BD migrada."""
    return RepositorioAbstenciones(conexion)


@pytest.fixture
def guardian(repo_presencia, repo_abstenciones):
    """Guardián con los umbrales por defecto (30% caída, 70 mínimo)."""
    return GuardianRecuento(
        repositorio_presencia=repo_presencia,
        abstenciones=repo_abstenciones,
        umbral_caida_pct=30,
        recuento_minimo=70,
    )


TS = "2026-11-22T01:30:00+00:00"
TS2 = "2026-11-23T01:30:00+00:00"


# ---------------------------------------------------------------------------
# Caso sin histórico (ALT-010)
# ---------------------------------------------------------------------------


class TestSinHistorico:
    """Sin recuento anterior: registrar y aplazar."""

    def test_sin_historico_no_permitido(self, guardian, repo_presencia):
        """Sin recuento anterior, validar devuelve permitido=False."""
        resultado = guardian.validar(recuento_actual=93, timestamp=TS)
        assert resultado.permitido is False
        assert resultado.motivo_abstencion is not None
        assert "recuento anterior" in resultado.motivo_abstencion.lower() or "aplaza" in resultado.motivo_abstencion.lower()

    def test_sin_historico_registra_recuento(self, guardian, repo_presencia):
        """Sin recuento anterior, se registra el actual en la serie."""
        guardian.validar(recuento_actual=93, timestamp=TS)
        ultimo = repo_presencia.obtener_ultimo_recuento()
        assert ultimo == (93, TS)

    def test_sin_historico_no_registra_abstencion_en_repositorio(
        self, guardian, repo_abstenciones
    ):
        """Sin recuento anterior, se aplaza pero NO se registra abstención
        en el repositorio (es un aplazamiento, no una abstención por caída)."""
        guardian.validar(recuento_actual=93, timestamp=TS)
        ultimas = repo_abstenciones.consultar_ultimas()
        # El aplazamiento por ALT-010 no registra en abstenciones_cierre:
        # solo registra el recuento en la serie.
        assert len(ultimas) == 0


# ---------------------------------------------------------------------------
# Caída menor al umbral → permitido
# ---------------------------------------------------------------------------


class TestCaidaMenorAlUmbral:
    """Caída dentro del umbral: se permite el cierre."""

    def test_caida_pequena_permitido(
        self, guardian, repo_presencia
    ):
        """Anterior 93 y actual 92 → caída ~1.07%, permitido."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=92, timestamp=TS)
        assert resultado.permitido is True
        assert resultado.motivo_abstencion is None

    def test_mismo_recuento_permitido(
        self, guardian, repo_presencia
    ):
        """Mismo recuento (sin caída) → permitido."""
        repo_presencia.registrar_recuento(100, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=100, timestamp=TS)
        assert resultado.permitido is True

    def test_recuento_mayor_permitido(
        self, guardian, repo_presencia
    ):
        """Recuento mayor que el anterior → permitido (no hay caída)."""
        repo_presencia.registrar_recuento(80, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=90, timestamp=TS)
        assert resultado.permitido is True

    def test_registra_recuento_actual_en_serie(
        self, guardian, repo_presencia
    ):
        """Tras validar permitido, la serie refleja el recuento actual."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        guardian.validar(recuento_actual=92, timestamp=TS)
        ultimo = repo_presencia.obtener_ultimo_recuento()
        assert ultimo == (92, TS)


# ---------------------------------------------------------------------------
# Caída mayor al umbral → abstención
# ---------------------------------------------------------------------------


class TestCaidaMayorAlUmbral:
    """Caída que supera el umbral: abstención (REQ-008, ALT-002)."""

    def test_caida_grande_abstencion(
        self, guardian, repo_presencia
    ):
        """Anterior 93 y actual 60 → abstención (por mínimo, 60 < 70).

        Con estos valores ambos criterios se cumplen (caída ~35.5% > 30%
        y actual 60 < mínimo 70), pero la comprobación de mínimo tiene
        prioridad. Lo importante es que el cierre queda bloqueado
        (REQ-008, ALT-002).
        """
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=60, timestamp=TS)
        assert resultado.permitido is False
        assert resultado.motivo_abstencion is not None

    def test_caida_grande_registra_abstencion(
        self, guardian, repo_presencia, repo_abstenciones
    ):
        """La abstención se registra con anterior/actual/umbral (REQ-011)."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        guardian.validar(recuento_actual=60, timestamp=TS)
        ultimas = repo_abstenciones.consultar_ultimas()
        assert len(ultimas) == 1
        abst = ultimas[0]
        assert abst.recuento_anterior == 93
        assert abst.recuento_actual == 60
        assert abst.umbral_aplicado is not None
        assert "30" in abst.umbral_aplicado
        assert abst.timestamp == TS

    def test_caida_porcentual_sin_tocar_minimo(
        self, guardian, repo_presencia
    ):
        """Caída > 30% con actual >= mínimo: solo salta el umbral de caída.

        Anterior 200, actual 139 → caída = 30.5% > 30%, actual 139 >= 70.
        """
        repo_presencia.registrar_recuento(200, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=139, timestamp=TS)
        assert resultado.permitido is False
        assert "caída" in resultado.motivo_abstencion.lower() or "30.5" in resultado.motivo_abstencion

    def test_caida_en_el_limite_exacto_permitido(
        self, guardian, repo_presencia
    ):
        """Caída exactamente igual al umbral (30%) → no es >, permitido.

        Con anterior=100 y actual=70: caída = (100-70)/100*100 = 30.0%.
        La condición es '>', así que 30.0 no es > 30 → permitido.
        """
        repo_presencia.registrar_recuento(100, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=70, timestamp=TS)
        assert resultado.permitido is True


# ---------------------------------------------------------------------------
# Recuento mínimo no alcanzado → abstención
# ---------------------------------------------------------------------------


class TestRecuentoMinimo:
    """Recuento actual inferior al mínimo: abstención (REQ-008)."""

    def test_actual_inferior_al_minimo_abstencion(
        self, guardian, repo_presencia
    ):
        """Actual 65 con anterior 93 → 65 < 70 → abstención por mínimo."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=65, timestamp=TS)
        assert resultado.permitido is False
        assert resultado.motivo_abstencion is not None
        assert "mínimo" in resultado.motivo_abstencion or "minimo" in resultado.motivo_abstencion

    def test_actual_igual_al_minimo_permitido(
        self, guardian, repo_presencia
    ):
        """Actual igual al mínimo (70) → no es <, permitido.

        Verifica que la condición es estrictamente menor.
        """
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        resultado = guardian.validar(recuento_actual=70, timestamp=TS)
        assert resultado.permitido is True

    def test_minimo_registra_abstencion_con_datos(
        self, guardian, repo_presencia, repo_abstenciones
    ):
        """La abstención por mínimo se registra con anterior/actual/umbral."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        guardian.validar(recuento_actual=65, timestamp=TS)
        ultimas = repo_abstenciones.consultar_ultimas()
        assert len(ultimas) == 1
        abst = ultimas[0]
        assert abst.recuento_anterior == 93
        assert abst.recuento_actual == 65
        assert "70" in abst.umbral_aplicado


# ---------------------------------------------------------------------------
# Umbrales personalizados (NFR-003)
# ---------------------------------------------------------------------------


class TestUmbralesPersonalizados:
    """Con umbrales configurados distintos a los por defecto."""

    @pytest.fixture
    def guardian_strict(
        self, repo_presencia, repo_abstenciones
    ):
        """Guardián con umbral 20% y mínimo 80."""
        return GuardianRecuento(
            repositorio_presencia=repo_presencia,
            abstenciones=repo_abstenciones,
            umbral_caida_pct=20,
            recuento_minimo=80,
        )

    def test_umbral_20_porciento_se_aplica(
        self, guardian_strict, repo_presencia
    ):
        """Con umbral 20%, caída de 25% → abstención.

        Anterior 200, actual 150 → caída = 25% > 20%.
        El actual (150) supera el mínimo (80) para que solo salte el umbral.
        """
        repo_presencia.registrar_recuento(200, "2026-11-21T01:30:00+00:00")
        resultado = guardian_strict.validar(
            recuento_actual=150, timestamp=TS
        )
        assert resultado.permitido is False
        assert "caída" in resultado.motivo_abstencion.lower() or "25" in resultado.motivo_abstencion

    def test_minimo_80_se_aplica(
        self, guardian_strict, repo_presencia
    ):
        """Con mínimo 80, actual 79 → abstención por mínimo."""
        repo_presencia.registrar_recuento(100, "2026-11-21T01:30:00+00:00")
        resultado = guardian_strict.validar(
            recuento_actual=79, timestamp=TS
        )
        assert resultado.permitido is False

    def test_dentro_de_umbrales_strict_permitido(
        self, guardian_strict, repo_presencia
    ):
        """Con umbral 20% y mínimo 80, caída 10% y actual 90 → permitido."""
        repo_presencia.registrar_recuento(100, "2026-11-21T01:30:00+00:00")
        resultado = guardian_strict.validar(
            recuento_actual=90, timestamp=TS
        )
        assert resultado.permitido is True


# ---------------------------------------------------------------------------
# Registro de recuentos y abstenciones
# ---------------------------------------------------------------------------


class TestRegistros:
    """Verificación del registro de recuentos y abstenciones."""

    def test_recuento_se_registra_siempre(
        self, guardian, repo_presencia
    ):
        """El recuento actual se registra tanto si se permite como si no."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        guardian.validar(recuento_actual=60, timestamp=TS)  # abstención
        ultimo = repo_presencia.obtener_ultimo_recuento()
        assert ultimo == (60, TS)

    def test_abstencion_no_se_registra_si_permitido(
        self, guardian, repo_presencia, repo_abstenciones
    ):
        """Si se permite el cierre, no se registra abstención."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        guardian.validar(recuento_actual=92, timestamp=TS)
        ultimas = repo_abstenciones.consultar_ultimas()
        assert len(ultimas) == 0

    def test_multiples_validaciones_registran_serie(
        self, guardian, repo_presencia
    ):
        """Múltiples validaciones van añadiendo a la serie."""
        repo_presencia.registrar_recuento(100, "2026-11-20T01:30:00+00:00")
        guardian.validar(recuento_actual=95, timestamp=TS)
        guardian.validar(recuento_actual=93, timestamp=TS2)
        ultimo = repo_presencia.obtener_ultimo_recuento()
        assert ultimo == (93, TS2)


# ---------------------------------------------------------------------------
# No escribe en la base de datos de ofertas (SUP-003)
# ---------------------------------------------------------------------------


class TestNoEscribeEnOfertas:
    """El guardián no escribe en la base de datos de ofertas."""

    def test_no_existe_tabla_ofertas(self, conexion):
        """La BD del histórico no contiene la tabla 'ofertas'."""
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas

    def test_tras_validar_no_aparece_ofertas(
        self, guardian, repo_presencia, conexion
    ):
        """Tras ejecutar validaciones, no aparece la tabla 'ofertas'."""
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        guardian.validar(recuento_actual=60, timestamp=TS)
        guardian.validar(recuento_actual=92, timestamp=TS2)
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas
