package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.chaquo.python.Python
import com.example.pokemmobreederhelper.data.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Test

class LiveInventoryRepositoryTest {
  private fun application(): Application {
    val base=ApplicationProvider.getApplicationContext<Application>()
    val folder=File(base.cacheDir,"live-inventory-"+System.nanoTime()).also { it.mkdirs() }
    return object:Application() {
      init { attachBaseContext(base) }
      override fun getApplicationContext(): Context=this
      override fun getFilesDir():File=folder
    }
  }
  private val pet=MonsterRecord(id="capture",species="伊布",gender="F",nature="固执",ivs=listOf(31,31,20,0,15,31),
    account="合成账号",page="2",slot="7",source="mobile-live",verified=false,
    createdAt="2026-11-10T10:00:00",updatedAt="2026-11-10T10:00:00")

  @Test fun serviceAndActivityNeverOverwriteEachOthersInventoryAndRoute() {
    val app=application();val activity=InventoryRepository(app);val service=InventoryRepository(app)
    val seed=pet.copy(id="seed",slot="1",verified=true)
    activity.replace(WorkspaceSnapshot(listOf(seed)))
    val observed=activity.inventory
    val executor=Executors.newFixedThreadPool(2);val start=CountDownLatch(1)
    try {
      val incoming=executor.submit { start.await();repeat(10) { n ->
        service.insertCapture(pet.copy(id="capture-"+n,slot=(n+2).toString()))
      } }
      val edit=executor.submit { start.await();activity.updateInventory { items ->
        items.map { if(it.id=="seed") it.copy(notes="界面修改") else it }
      } }
      start.countDown();incoming.get();edit.get()
      assertEquals(11,observed.value.size)
      assertEquals("界面修改",service.inventory.value.first().notes)
      assertEquals(observed.value,InventoryRepository(app).inventory.value)
      assertEquals(11,AppJson.decodeInventory(activity.inventoryJson()).size)
    } finally { executor.shutdownNow() }
  }
  @Test fun duplicatePositionDoesNotOverwriteAndCapturedRecordsRemainUnconfirmed() {
    val repo=InventoryRepository(application())
    assertEquals(CaptureInsertResult.ADDED,repo.insertCapture(pet.copy(verified=true)))
    assertFalse(repo.inventory.value.single().verified)
    assertEquals(CaptureInsertResult.ALREADY_PRESENT,repo.insertCapture(pet.copy(id="second")))
    assertEquals(CaptureInsertResult.SLOT_OCCUPIED,repo.insertCapture(pet.copy(id="third",nature="胆小")))
    assertEquals(CaptureInsertResult.ADDED,repo.insertCapture(pet.copy(id="fourth",slot="8")))
    assertEquals(2,repo.inventory.value.size)
    assertTrue(repo.undo());assertEquals(listOf(pet),repo.inventory.value)
  }
  @Test fun staleEggCompletionCannotEraseNewCapture() {
    val repo=InventoryRepository(application());val before=repo.inventory.value
    repo.insertCapture(pet)
    assertThrows(IllegalStateException::class.java) { repo.replace(WorkspaceSnapshot(emptyList()),expectedInventory=before) }
    assertEquals(listOf(pet),repo.inventory.value)
  }
  @Test fun exportedJsonRoundTripsThroughActualDesktopModelWithoutLosingFields() {
    val app=application();val repo=InventoryRepository(app)
    val complete=pet.copy(ability="危险预知",heldItem="不变之石",moves=listOf("祈愿","哈欠"),eggGroups=listOf("陆上"),
      isAlpha=true,hasHiddenAbility=true,notes="合成往返测试",confidence=0.91,breedingTargetKey="fixture-target",
      breedingRole="nature",natureAttemptLevel=4,natureAttemptResult="hit",genderUnconfirmed=true,
      scanFingerprint="fixture-fingerprint",createdAt="2026-11-10T10:00:00",updatedAt="2026-11-10T11:00:00")
    repo.replace(WorkspaceSnapshot(listOf(complete,pet.copy(id="unknown",ivs=listOf(null,0,1,30,31,null),slot="9"))))
    PlannerBridge(app)
    val python=Python.getInstance();val json=python.getModule("json");val monster=python.getModule("models").get("Monster")!!
    val desktop=json.callAttr("loads",repo.inventoryJson()).asList().map { monster.callAttr("from_dict",it).callAttr("to_dict") }
    val returned=desktop.joinToString(prefix="[",postfix="]") { json.callAttr("dumps",it).toString() }
    val target=InventoryRepository(application());target.importInventory(returned)
    assertEquals(repo.inventory.value,target.inventory.value)
    assertEquals(listOf(false,false),target.inventory.value.map { it.verified })
  }
}
