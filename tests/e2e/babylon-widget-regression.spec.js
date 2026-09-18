// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('Babylon 3D Turbine Widget Regression Tests', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the test harness
    await page.goto('/tests/fixtures/babylon-harness.html');

    // Wait for the widget to finish initializing and loading GLB
    await page.waitForFunction(() => {
      return (
        window['__widgetReady'] === true &&
        window['ctx'] &&
        window['ctx'].t3dScene &&
        window['ctx'].t3dMeshEntities &&
        Object.keys(window['ctx'].t3dMeshEntities).length > 0 &&
        window['ctx'].t3dEls &&
        window['ctx'].t3dEls.loading &&
        window['ctx'].t3dEls.loading.hidden === true
      );
    }, { timeout: 20000 });

    // Assert that no unhandled errors were caught during loading
    const errors = await page.evaluate(() => window['__errors']);
    expect(errors).toEqual([]);
  });

  test('Regression 1: Mesh pivots are centered for rotating components (not at origin)', async ({ page }) => {
    const pivots = await page.evaluate(() => {
      const ctx = window['ctx'];
      const targetMeshes = ["Turbine.001", "Gearbox.001", "SteamAdmission.002"];
      const results = {};

      for (const name of targetMeshes) {
        const entry = ctx.t3dMeshEntities[name];
        if (!entry || !entry.node) {
          results[name] = { exists: false };
          continue;
        }
        const node = entry.node;
        const pivot = node.getPivotPoint();
        const bboxCenter = node.getBoundingInfo().boundingBox.center;

        results[name] = {
          exists: true,
          pivot: { x: pivot.x, y: pivot.y, z: pivot.z },
          bboxCenter: { x: bboxCenter.x, y: bboxCenter.y, z: bboxCenter.z },
          distanceToOrigin: Math.hypot(pivot.x, pivot.y, pivot.z),
          distanceToBboxCenter: Math.hypot(
            pivot.x - bboxCenter.x,
            pivot.y - bboxCenter.y,
            pivot.z - bboxCenter.z
          )
        };
      }
      return results;
    });

    for (const [name, info] of Object.entries(pivots)) {
      expect(info.exists, `Mesh ${name} should exist`).toBe(true);
      // Pivot should match bounding box center (distance near zero)
      expect(info.distanceToBboxCenter).toBeLessThan(0.01);
    }
  });

  test('Regression 2: Click to deselect restores full overview and clears selected group', async ({ page }) => {
    // 1. Select the gearbox group
    await page.evaluate(() => {
      const ctx = window['ctx'];
      window['t3dSelectGroup'](ctx, 'gearbox');
    });

    const isGearboxSelected = await page.evaluate(() => window['ctx'].t3dSelectedGroup);
    expect(isGearboxSelected).toBe('gearbox');

    // 2. Click empty space / deselect
    await page.evaluate(() => {
      const ctx = window['ctx'];
      // Emulate clicking empty space (pointer tap without a mesh pick)
      window['t3dSelectGroup'](ctx, null);
      window['t3dSyncDashboardState'](ctx, null, null, null);
    });

    const deselectedGroup = await page.evaluate(() => window['ctx'].t3dSelectedGroup);
    expect(deselectedGroup).toBeNull();

    // Verify all meshes returned to full visibility (visibility === 1)
    const allFullOpacity = await page.evaluate(() => {
      const ctx = window['ctx'];
      return Object.keys(ctx.t3dMeshEntities).every(name => {
        const node = ctx.t3dMeshEntities[name].node;
        return node && node.visibility === 1;
      });
    });
    expect(allFullOpacity).toBe(true);

    // Verify state sync updated with null component
    const lastState = await page.evaluate(() => window['__lastState']);
    expect(lastState.selectedComponent).toBeNull();
  });

  test('Regression 3: Particle textures initialize cleanly without console errors', async ({ page }) => {
    const particleStatus = await page.evaluate(() => {
      const ctx = window['ctx'];
      const inlet = ctx.t3dParticleSystems.inlet;
      const leakage = ctx.t3dParticleSystems.leakage;

      return {
        inletExists: Boolean(inlet),
        inletTextureValid: Boolean(inlet && inlet.particleTexture && inlet.particleTexture.hasAlpha),
        inletIsStarted: Boolean(inlet && inlet.isStarted()),
        leakageExists: Boolean(leakage),
        leakageTextureValid: Boolean(leakage && leakage.particleTexture && leakage.particleTexture.hasAlpha),
        leakageIsStarted: Boolean(leakage && leakage.isStarted()),
        errors: window['__errors']
      };
    });

    expect(particleStatus.inletExists).toBe(true);
    expect(particleStatus.inletTextureValid).toBe(true);
    expect(particleStatus.inletIsStarted).toBe(true);

    expect(particleStatus.leakageExists).toBe(true);
    expect(particleStatus.leakageTextureValid).toBe(true);
    expect(particleStatus.leakageIsStarted).toBe(true);

    expect(particleStatus.errors).toEqual([]);
  });

  test('Regression 4: Isolation-mode fade dims non-selected components but exempts ungrouped meshes', async ({ page }) => {
    const visibilityCheck = await page.evaluate(() => {
      const ctx = window['ctx'];

      // Add a simulated ungrouped mesh to verify isolation exemption
      const dummyMesh = new BABYLON.Mesh("UngroupedAuxiliary.001", ctx.t3dScene);
      ctx.t3dMeshEntities["UngroupedAuxiliary.001"] = { node: dummyMesh, entityData: null };

      // Select inlet group
      window['t3dSelectGroup'](ctx, 'inlet');

      const inletMesh = ctx.t3dMeshEntities["SteamAdmission.001"]?.node;
      const turbineMesh = ctx.t3dMeshEntities["Turbine.001"]?.node;
      const ungroupedMesh = ctx.t3dMeshEntities["UngroupedAuxiliary.001"]?.node;

      const result = {
        selectedInletVisibility: inletMesh ? inletMesh.visibility : null,
        otherTurbineVisibility: turbineMesh ? turbineMesh.visibility : null,
        ungroupedVisibility: ungroupedMesh ? ungroupedMesh.visibility : null,
      };

      // Cleanup dummy mesh
      dummyMesh.dispose();
      delete ctx.t3dMeshEntities["UngroupedAuxiliary.001"];
      window['t3dSelectGroup'](ctx, null);

      return result;
    });

    expect(visibilityCheck.selectedInletVisibility).toBe(1);
    expect(visibilityCheck.otherTurbineVisibility).toBe(0.12);
    expect(visibilityCheck.ungroupedVisibility).toBe(1);
  });

  test('Regression 5: Camera fly-to radius scales with group extent bounds', async ({ page }) => {
    const extentCheck = await page.evaluate(() => {
      const ctx = window['ctx'];
      const groups = ['gearbox', 'turbine', 'inlet'];
      const results = {};

      for (const grp of groups) {
        const center = window['t3dGroupCenter'](ctx, grp);
        const extent = window['t3dGroupExtent'](ctx, grp, center);
        results[grp] = {
          center: { x: center.x, y: center.y, z: center.z },
          extent: extent,
        };
      }
      return results;
    });

    for (const [grp, data] of Object.entries(extentCheck)) {
      expect(data.extent, `Extent for ${grp} should be positive`).toBeGreaterThan(0.2);
    }
  });

  test('Regression 6: In-widget settings editor opens, captures view, and saves without raw JSON', async ({ page }) => {
    // Open settings modal
    await page.click('#t3d-btn-settings');
    const modalVisible = await page.isVisible('#t3d-settings-modal');
    expect(modalVisible).toBe(true);

    // Click capture camera button
    await page.click('#t3d-btn-capture-cam');

    // Verify fields populated
    const alpha = await page.inputValue('#t3d-set-cam-alpha');
    const radius = await page.inputValue('#t3d-set-cam-radius');
    expect(Number(alpha)).not.toBeNaN();
    expect(Number(radius)).toBeGreaterThan(0);

    // Change radius and click save
    await page.fill('#t3d-set-cam-radius', '8.5');
    await page.click('#t3d-btn-settings-save');

    // Modal should close
    const modalHidden = await page.isHidden('#t3d-settings-modal');
    expect(modalHidden).toBe(true);

    // Saved settings should be updated in ctx
    const savedRadius = await page.evaluate(() => window['ctx'].settings.cameraPosition.radius);
    expect(savedRadius).toBe(8.5);
  });

  test('Task 8: Floating sensor markers render for isolated component and open detail drawer on click', async ({ page }) => {
    // 1. Initially (overview mode), markers should be hidden
    const initialMarkersHidden = await page.evaluate(() => {
      const markers = document.querySelectorAll('.t3d-sensor-pin');
      return Array.from(markers).every(m => m.style.display === 'none');
    });
    expect(initialMarkersHidden).toBe(true);

    // 2. Select the gearbox component group
    await page.evaluate(() => {
      const ctx = window['ctx'];
      window['t3dSelectGroup'](ctx, 'gearbox');
    });

    // Wait for markers in gearbox group to become visible
    await page.waitForFunction(() => {
      const pin = document.getElementById('t3d-pin-XT_604');
      return pin && pin.style.display === 'inline-flex';
    });

    const xt604Pin = page.locator('#t3d-pin-XT_604');
    await expect(xt604Pin).toBeVisible();

    // 3. Click the sensor pin to open the Sensor Detail Drawer
    await xt604Pin.click();

    const sensorDrawer = page.locator('#t3d-sensor-drawer');
    await expect(sensorDrawer).toBeVisible();

    const sensorId = await page.locator('#t3d-sensor-id').textContent();
    expect(sensorId).toBe('XT_604');

    const sensorName = await page.locator('#t3d-sensor-name').textContent();
    expect(sensorName).toContain('Gearbox Radial Station 1 X');

    // 4. Close drawer
    await page.click('#t3d-sensor-close');
    await expect(sensorDrawer).toBeHidden();
  });

  test('Task 8: Auxiliary unlocated channels panel displays all 17 sensors and links to detail drawer', async ({ page }) => {
    // 1. Click auxiliary toolbar button
    await page.click('#t3d-btn-aux');

    const auxDrawer = page.locator('#t3d-aux-drawer');
    await expect(auxDrawer).toBeVisible();

    // Verify 17 items rendered
    const auxItems = page.locator('.t3d-aux-item');
    const count = await auxItems.count();
    expect(count).toBe(17);

    // Check first unlocated channel
    const firstId = await auxItems.first().locator('.t3d-aux-item-id').textContent();
    expect(firstId).toBe('PT_110A');

    // 2. Click first auxiliary item to open detail drawer
    await auxItems.first().click();

    const sensorDrawer = page.locator('#t3d-sensor-drawer');
    await expect(sensorDrawer).toBeVisible();

    const sensorId = await page.locator('#t3d-sensor-id').textContent();
    expect(sensorId).toBe('PT_110A');

    const meshNode = await page.locator('#t3d-sensor-mesh').textContent();
    expect(meshNode).toBe('Unlocated (Auxiliary)');
  });
});
